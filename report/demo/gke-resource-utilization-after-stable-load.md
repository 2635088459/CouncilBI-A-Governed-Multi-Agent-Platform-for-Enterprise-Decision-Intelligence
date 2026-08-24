# GKE Resource Utilization After Stable Sustained Load

- Workload: 10-minute sustained benchmark, 0.8 target RPS, concurrency 2
- Successful requests: 480/480

## Pods

```text
NAME                        CPU(cores)   MEMORY(bytes)
backend-58486cf7b8-7cn4m    6m           115Mi
backend-58486cf7b8-hth6c    7m           120Mi
frontend-8656dbbd94-jzkx4   1m           8Mi
postgres-7485d97cf-6856k    7m           69Mi
redis-75849bf788-kpsfz      10m          8Mi
worker-d874f4cf8-clnw5      0m           9Mi
```

## Nodes

```text
NAME                                      CPU(cores)   CPU(%)   MEMORY(bytes)   MEMORY(%)
gk3-chatbi-staging-pool-3-99d9705a-d9hn   408m         2%       3424Mi          5%
```

## HPA

```text
NAME      REFERENCE            TARGETS       MINPODS   MAXPODS   REPLICAS   AGE
backend   Deployment/backend   cpu: 1%/70%   2         6         2          159m
```
