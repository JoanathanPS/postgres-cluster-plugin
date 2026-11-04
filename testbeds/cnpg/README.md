# CloudNativePG test bed

```powershell
kind create cluster --name cnpg-test
kubectl apply --server-side -f https://github.com/cloudnative-pg/cloudnative-pg/releases/download/v1.24.1/cnpg-1.24.1.yaml
kubectl apply -f testbeds/cnpg/cluster.yaml
kubectl wait --for=condition=Ready cluster/cnpg-test --timeout=600s
python tester/test_discovery_live.py cloudnative
```

The plugin runs inside the Kubernetes network as a pod (the test script does this). Remove with `kind delete cluster --name cnpg-test`.
