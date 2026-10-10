import socket
host="192.168.1.10"
def req(p, path="/"):
    try:
        s=socket.socket(); s.settimeout(2.5); s.connect((host,p))
        s.sendall(b"GET %b HTTP/1.1\r\nHost: %b\r\nUser-Agent: curl/8\r\nConnection: close\r\n\r\n"%(path.encode(),host.encode()))
        buf=b""
        while len(buf)<2048:
            try:
                d=s.recv(1024)
                if not d: break
                buf+=d
            except: break
        s.close()
        return buf
    except Exception as e:
        return f"ERR {e}".encode()
for p in [38400,39259]:
    for path in ["/","/description.xml","/dmr.xml","/index.html","/info","/apps","/status","/server","/version"]:
        r=req(p,path)
        head=r.split(b"\r\n\r\n",1)
        line=r.split(b"\r\n",1)[0]
        body=head[1][:120] if len(head)>1 else b""
        print(p,path,"|",line.decode(errors="replace"),"|",body[:120], flush=True)
