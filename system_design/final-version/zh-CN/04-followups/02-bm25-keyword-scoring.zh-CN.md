# 4.2 用真正的 BM25 替换 Jaccard 式关键词重叠打分

## 1. 解决的问题

混合检索公式里"关键词"那一半,其实不是一个真正的词权重算法——它只是一个把每个 token 都当作同等重要的集合交集比例。一个稀有但高信号的领域词(比如某条具体的保险条款用语)得分不会比查询恰好共享的任何常见词更高。本文档用 BM25——标准的词频/逆文档频率排序算法——替换它,同时不改动 [4.1](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md) 里已经设计好的混合融合架构。

## 2. 现状梳理

`InMemoryKnowledgeStore._rank_records()`([src/chatbi/knowledge.py:341-363](../../../../src/chatbi/knowledge.py))对每个候选 chunk 计算:

```python
keyword_score = keyword_overlap_score(query_tokens, text_tokens(record.chunk.chunk_text))
vector_score = cosine_similarity(...)
relevance_score = round((keyword_score * 0.60) + (vector_score * 0.35) + source_score, 4)
```

`keyword_overlap_score()`([knowledge.py:505-511](../../../../src/chatbi/knowledge.py))是:

```python
return len(query_set & chunk_set) / len(query_set)
```

这是一个查询覆盖率(更接近召回导向的 Jaccard 变体),不是 BM25:它没有词频加权(一个词在 chunk 里出现 5 次和出现 1 次得分一样)、没有逆文档频率加权(一个在语料库里很罕见的词和一个很常见的词得分一样)、也没有文档长度归一化(一个精确切题的短 chunk 和一个恰好包含同样 token 集合的长 chunk 得分一样)。`text_tokens()`([knowledge.py:501-502](../../../../src/chatbi/knowledge.py))用 `re.findall(r"[a-z0-9]+", text.lower())` 分词——只认 ASCII,也就是说今天所有中文 token 在关键词打分里都会被静默丢弃,这对一个访谈问答记录和相当一部分自身 spec 语料都是中文的平台来说是个实实在在的缺口。

在 `src/` 里全仓搜索,没有任何地方出现"BM25"或"倒排索引"——这是一个全新算法,不是改名。

## 3. 设计方案

1. **新增 `rank_bm25` 依赖**(纯 Python 实现的 `BM25Okapi`,不需要额外服务——鉴于项目目前的内存检索规模,这样做是合适的;只有当语料库大到单进程内存放不下时才需要重新考虑)。
2. **在"已经过权限过滤的候选集合"上构建 BM25 索引**,而不是一个预先构建好的全局索引。`_rank_records()` 接收的 `filtered_records` 是 `list_chunk_records()`([knowledge.py:218-255](../../../../src/chatbi/knowledge.py))的输出,已经完成了组织/角色/所有者的可见性过滤。BM25 必须在同一个受限候选列表内打分,否则用户看不到的文档仍可能通过语料库级别的 IDF 统计,以某种方式泄露它的存在。具体做法:`BM25Okapi([tokenize(r.chunk.chunk_text) for r in filtered_records])`,每次请求都现建。这会以少量每次查询的 CPU 开销换取正确性;因为不是持久化索引,所以也没有陈旧/失效需要管理的问题。
3. **替换掉对中文不友好的分词方式。** 扩展 `text_tokens()` 的正则(或新增一个专供 BM25 使用的并行分词器),让它也能产出 CJK 单字/双字 token,使中文 chunk 和中文问题真正参与关键词打分,而不是贡献零个 token。
4. **把 BM25 无界的原始分数归一化,接入现有的 `[0, 1]` 左右的融合区间。** BM25 分数不像余弦相似度那样天然有界,需要在每次查询自己的候选集合内做 min-max 归一化,再应用现有的 `* 0.60` 权重,这样固定权重融合公式的假设(两项量级大致可比)才能继续成立。
5. **本文档不改动 0.60/0.35/source_score 权重**,理由同 [4.1 第3节](01-unifying-the-vector-and-hybrid-retrieval-paths.zh-CN.md#3-设计方案)——重新调优需要 [4.4](04-golden-dataset-hit-rate-and-mrr-evaluation.zh-CN.md) 的评估工具实测,而不是靠猜。

## 4. 工作量评估

大约 **0.5–1 人天**。这是四个阶段里最便宜的一个:是在一个已有接缝(`_rank_records` 已经把"关键词分数"隔离成单独一行)上做本地的替换实现,不需要新基础设施,唯一需要仔细处理的是 CJK 分词器扩展部分(至少要拿 seed 数据里已有的一份中文知识文档验证一下)。

## 5. 需求编号

| ID | 需求 | 状态 |
|---|---|---|
| FR-FV03-018 | 关键词打分必须使用 BM25(词频/逆文档频率/长度归一化),在每次请求的权限过滤候选集合上计算,而不是预先构建的全局索引。 | 待实现 |
| FR-FV03-019 | 关键词分词必须支持中文文本,不能只支持 ASCII 单词 token。 | 待实现 |
| FR-FV03-020 | 在应用 0.60/0.35 融合权重之前,BM25 分数必须归一化到与现有余弦相似度分量可比的区间。 | 待实现 |
