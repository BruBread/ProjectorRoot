import socket
host="192.168.1.10"
ports=[3268,11022,11101,11102,11103,11104,33031,38400,38653,38871,39259,42869,62110]
def grab(p):
    out=b""
    # try raw read first (server-speaks-first like SSH)
    try:
        s=socket.socket(); s.settimeout(2.0); s.connect((host,p))
        try: out=s.recv(256)
        except: out=b""
        if not out:
            # try HTTP GET
            try:
                s.sendall(b"GET / HTTP/1.0\r\nHost: %b\r\n\r\n"%host.encode())
                out=s.recv(256)
            except: pass
        s.close()
    except Exception as e:
        return f"{p}: ERR {e}"
    return f"{p}: {out[:160]!r}"
for p in ports:
    print(grab(p), flush=True)
