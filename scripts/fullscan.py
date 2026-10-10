import socket
from concurrent.futures import ThreadPoolExecutor
host="192.168.1.10"
def probe(p):
    s=socket.socket(); s.settimeout(0.8)
    try:
        if s.connect_ex((host,p))==0: return p
    finally: s.close()
open_ports=[]
with ThreadPoolExecutor(200) as ex:
    for r in ex.map(probe, range(1,65536)):
        if r: open_ports.append(r); print("OPEN", r, flush=True)
print("DONE open=", sorted(open_ports), flush=True)
