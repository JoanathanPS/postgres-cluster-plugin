import sys
sys.path.insert(0, r'postgres_cluster')
import postgres_cluster

cfg_path = r'C:\Program Files (x86)\Site24x7\WinAgent\monitoring\Plugins\postgres_cluster_v6\postgres_cluster_v6.cfg'
print(postgres_cluster.read_cfg_file(cfg_path))
