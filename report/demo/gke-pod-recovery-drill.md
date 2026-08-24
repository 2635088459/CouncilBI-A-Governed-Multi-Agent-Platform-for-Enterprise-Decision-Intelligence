# GKE Pod Recovery Drill

- Deleted backend pod: backend-58486cf7b8-267zh
- Recovery time seconds: 21
- Post-recovery chat query HTTP status: 200

## Rollout Output

Waiting for deployment "backend" rollout to finish: 1 of 2 updated replicas are available...
deployment "backend" successfully rolled out

## Current Pods

NAME                        READY   STATUS    RESTARTS   AGE
backend-58486cf7b8-7cn4m    1/1     Running   0          22s
backend-58486cf7b8-hth6c    1/1     Running   0          94m
frontend-8656dbbd94-jzkx4   1/1     Running   0          94m
postgres-7485d97cf-6856k    1/1     Running   0          94m
redis-75849bf788-kpsfz      1/1     Running   0          94m
worker-d874f4cf8-clnw5      1/1     Running   0          94m
