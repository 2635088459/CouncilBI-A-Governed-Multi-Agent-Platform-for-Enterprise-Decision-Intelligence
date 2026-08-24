import { bg, C, connector, footer, node, rule, text, title } from "./theme.mjs";

export async function slide02(presentation) {
  const slide = presentation.slides.add();
  bg(slide);
  title(slide, "The LLM sits behind governed routing, bounded data, and audit gates.", "ARCHITECTURE");
  const y = 245;
  node(slide, "Business question", "Natural-language BI request with user, role, org, and session context.", 64, y, 150, 116, C.white);
  node(slide, "Orchestrator", "Classifies intent and builds an agent plan instead of sending raw enterprise context.", 268, y, 150, 116, C.paleBlue);
  node(slide, "SQL guardrail", "Read-only validation, table allow-list, row limit, timeout policy, audit record.", 472, y, 160, 116, C.paleAmber);
  node(slide, "RAG evidence", "BM25/embedding retrieval selects only top snippets and citations.", 686, y, 150, 116, C.paleGreen);
  node(slide, "Answer verifier", "Checks grounded answer, traces every step, returns warnings when needed.", 890, y, 160, 116, C.white);
  node(slide, "User answer", "Chart/table/text response with trace_id for admin observability.", 1104, y, 120, 116, C.paleBlue);
  connector(slide, 214, y + 58, 268);
  connector(slide, 418, y + 58, 472);
  connector(slide, 632, y + 58, 686);
  connector(slide, 836, y + 58, 890);
  connector(slide, 1050, y + 58, 1104);
  rule(slide, 64, 440, 1160);
  text(slide, "What this proves", 68, 468, 230, 30, { size: 18, bold: true });
  text(slide, "The architecture is designed to reduce risk and token usage before the model is called: SQL handles structured aggregation; RAG handles targeted evidence; guardrails block unsafe execution.", 300, 462, 820, 66, { size: 20, valign: "top" });
  text(slide, "Secret handling: OpenAI API key is injected into backend/worker by Kubernetes Secret, not committed into YAML.", 300, 548, 800, 40, { size: 16, color: C.muted });
  footer(slide, "Sources: README.md, k8s/chatbi-runtime.yaml, docs/deployment/cloud-kubernetes-runbook.md", 2);
  return slide;
}
