import struct, sys, zipfile

def read_string_pool(data, off, chunk_size):
    string_count, style_count, flags, strings_start, styles_start = struct.unpack_from('<IIIII', data, off + 8)
    is_utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from(f'<{string_count}I', data, off + 28)
    strings = []
    base = off + strings_start
    for o in offsets:
        p = base + o
        if is_utf8:
            # one or two bytes: char length (skip), then one or two bytes: byte length
            b0 = data[p]
            if b0 & 0x80:
                p += 2
            else:
                p += 1
            b0 = data[p]
            if b0 & 0x80:
                blen = ((b0 & 0x7f) << 8) | data[p+1]
                p += 2
            else:
                blen = b0
                p += 1
            s = data[p:p+blen].decode('utf-8', errors='replace')
        else:
            u0 = struct.unpack_from('<H', data, p)[0]
            if u0 & 0x8000:
                clen = ((u0 & 0x7fff) << 16) | struct.unpack_from('<H', data, p+2)[0]
                p += 4
            else:
                clen = u0
                p += 2
            s = data[p:p+clen*2].decode('utf-16-le', errors='replace')
        strings.append(s)
    return strings

TYPE_NAMES = {0x01: 'ref', 0x03: 'string', 0x10: 'int', 0x12: 'bool'}

def resolve_value(strings, raw_value, data_type, data):
    if raw_value != 0xFFFFFFFF:
        return strings[raw_value] if raw_value < len(strings) else f'<str#{raw_value}>'
    if data_type == 0x12:
        return 'true' if data != 0 else 'false'
    if data_type == 0x10:
        return str(data)
    if data_type == 0x03:
        return strings[data] if data < len(strings) else f'<str#{data}>'
    if data_type == 0x01:
        return f'@0x{data:08x}'
    return f'<0x{data:08x} type={data_type}>'

def dump_axml(data):
    off = 8  # skip XML chunk header (type,headerSize,size)
    strings = []
    out = []
    depth = 0
    while off < len(data):
        ctype, header_size, csize = struct.unpack_from('<HHI', data, off)
        chunk_end = off + csize
        if ctype == 0x0001:  # STRING_POOL
            strings = read_string_pool(data, off, csize)
        elif ctype == 0x0102:  # START_ELEMENT
            line, comment, ns, name, attr_start, attr_size, attr_count, id_idx, class_idx, style_idx = \
                struct.unpack_from('<IIiIHHHHHH', data, off + 8)
            tag = strings[name] if name < len(strings) else f'<str#{name}>'
            attrs = []
            aoff = off + 16 + attr_start
            for i in range(attr_count):
                a_ns, a_name, a_raw, a_size, a_res0, a_type, a_data = struct.unpack_from('<iIIHBBI', data, aoff)
                aname = strings[a_name] if a_name < len(strings) else f'<str#{a_name}>'
                aval = resolve_value(strings, a_raw, a_type, a_data)
                attrs.append(f'{aname}="{aval}"')
                aoff += 20
            out.append('  ' * depth + f'<{tag} {" ".join(attrs)}>')
            depth += 1
        elif ctype == 0x0103:  # END_ELEMENT
            depth -= 1
            line, comment, ns, name = struct.unpack_from('<IIiI', data, off + 8)
            tag = strings[name] if name < len(strings) else f'<str#{name}>'
            out.append('  ' * depth + f'</{tag}>')
        off = chunk_end if csize > 0 else off + header_size
    return '\n'.join(out)

if __name__ == '__main__':
    apk_path = sys.argv[1]
    with zipfile.ZipFile(apk_path) as z:
        manifest = z.read('AndroidManifest.xml')
    print(dump_axml(manifest))
