import struct
import binascii
import zlib
import heapq

# ==========================================
# 設定
# ==========================================
WIDTH = 1000
HEIGHT = 1000
OUTPUT_FILENAME = "handwritten_chaos.png"
# ==========================================

def create_handwritten_png(W, H, filename):
    pattern = bytearray([0x07, 0x0B, 0x0D, 0x11, 0x13])
    bytes_per_row = W * 3
    total_bytes = (bytes_per_row + 1) * H

    # 生データの構築
    data = bytearray(total_bytes)
    for row in range(H):
        idx = row * (bytes_per_row + 1)
        data[idx] = 1 if row == 0 else 3 
        for col in range(1, bytes_per_row + 1):
            data[idx + col] = pattern[(col - 1) % 5]

    adler = zlib.adler32(data)

    # LZ77 パサー
    tokens =[]
    pos = 0
    end = total_bytes
    
    while pos < end:
        best_len = 0
        best_dist = 0
        limit = min(258, end - pos)
        
        if pos >= (bytes_per_row + 1):
            dist = bytes_per_row + 1
            if data[pos:pos+limit] == data[pos-dist:pos-dist+limit]:
                best_len = limit; best_dist = dist
            else:
                l = 0
                while l < limit and data[pos+l] == data[pos-dist+l]: l += 1
                if l >= 3: best_len = l; best_dist = dist
                
        if pos >= 5:
            if data[pos:pos+limit] == data[pos-5:pos-5+limit]:
                l = limit
            else:
                l = 0
                while l < limit and data[pos+l] == data[pos-5+l]: l += 1
            if l >= best_len and l >= 3:
                best_len = l; best_dist = 5
                
        if best_len >= 3:
            tokens.append(('match', best_len, best_dist))
            pos += best_len
        else:
            tokens.append(('lit', data[pos]))
            pos += 1

    tokens.append(('lit', 256))

    # ハフマン辞書の構築
    length_table =[(3,257,0),(4,258,0),(5,259,0),(6,260,0),(7,261,0),(8,262,0),(9,263,0),(10,264,0),(11,265,1),(13,266,1),(15,267,1),(17,268,1),(19,269,2),(23,270,2),(27,271,2),(31,272,2),(35,273,3),(43,274,3),(51,275,3),(59,276,3),(67,277,4),(83,278,4),(99,279,4),(115,280,4),(131,281,5),(163,282,5),(195,283,5),(227,284,5),(258,285,0)]
    dist_table =[(1,0,0),(2,1,0),(3,2,0),(4,3,0),(5,4,1),(7,5,1),(9,6,2),(13,7,2),(17,8,3),(25,9,3),(33,10,4),(49,11,4),(65,12,5),(97,13,5),(129,14,6),(193,15,6),(257,16,7),(385,17,7),(513,18,8),(769,19,8),(1025,20,9),(1537,21,9),(2049,22,10),(3073,23,10),(4097,24,11),(6145,25,11),(8193,26,12),(12289,27,12),(16385,28,13),(24577,29,13)]

    def get_len_sym(l):
        for base, sym, ext in reversed(length_table):
            if l >= base: return sym, ext, l - base
    def get_dist_sym(d):
        for base, sym, ext in reversed(dist_table):
            if d >= base: return sym, ext, d - base

    lit_freq = {i: 0 for i in range(286)}
    dist_freq = {i: 0 for i in range(32)}

    encoded_tokens =[]
    for t in tokens:
        if t[0] == 'lit':
            lit_freq[t[1]] += 1
            encoded_tokens.append(t)
        else:
            _, l, d = t
            lsym, lext, lval = get_len_sym(l)
            dsym, dext, dval = get_dist_sym(d)
            lit_freq[lsym] += 1
            dist_freq[dsym] += 1
            encoded_tokens.append(('match', lsym, lext, lval, dsym, dext, dval))

    def build_huffman_lengths(freqs):
        class Node:
            def __init__(self, weight, sym=None, left=None, right=None):
                self.weight = weight; self.sym = sym; self.left = left; self.right = right
            def __lt__(self, other): return self.weight < other.weight
            
        nodes = [Node(w, sym=s) for s, w in freqs.items() if w > 0]
        if not nodes: return {s: 0 for s in freqs}
        if len(nodes) == 1:
            sym = nodes[0].sym
            dummy = sym + 1 if sym < max(freqs.keys()) else sym - 1
            return {sym: 1, dummy: 1}
            
        heapq.heapify(nodes)
        while len(nodes) > 1:
            n1 = heapq.heappop(nodes)
            n2 = heapq.heappop(nodes)
            heapq.heappush(nodes, Node(n1.weight + n2.weight, left=n1, right=n2))
        
        lengths = {s: 0 for s in freqs}
        def dfs(node, depth):
            if node.sym is not None: lengths[node.sym] = depth
            else: dfs(node.left, depth + 1); dfs(node.right, depth + 1)
        dfs(nodes[0], 0)
        return lengths

    lit_len = build_huffman_lengths(lit_freq)
    dist_len = build_huffman_lengths(dist_freq)
    
    def assign_codes(lengths):
        max_len = max(lengths.values()) if lengths.values() else 0
        bl_count = [0] * (max_len + 1)
        for l in lengths.values():
            if l > 0: bl_count[l] += 1
        code = 0; next_code = [0] * (max_len + 1)
        for bits in range(1, max_len + 1):
            code = (code + bl_count[bits - 1]) << 1
            next_code[bits] = code
        codes = {}
        for sym in sorted(lengths.keys()):
            l = lengths[sym]
            if l > 0:
                codes[sym] = next_code[l]
                next_code[l] += 1
        return codes

    lit_codes = assign_codes(lit_len)
    dist_codes = assign_codes(dist_len)

    hlit = max((s for s, l in lit_len.items() if l > 0), default=256)
    hdist = max((s for s, l in dist_len.items() if l > 0), default=0)
    tree_lengths = [lit_len.get(i, 0) for i in range(hlit + 1)] + [dist_len.get(i, 0) for i in range(hdist + 1)]

    cl_tokens =[]
    i = 0
    while i < len(tree_lengths):
        val = tree_lengths[i]
        if val == 0:
            count = 0
            while i + count < len(tree_lengths) and tree_lengths[i + count] == 0 and count < 138: count += 1
            if count >= 11: cl_tokens.append((18, count - 11)); i += count
            elif count >= 3: cl_tokens.append((17, count - 3)); i += count
            else: cl_tokens.append((0, None)); i += 1
        else:
            cl_tokens.append((val, None)); i += 1
            count = 0
            while i + count < len(tree_lengths) and tree_lengths[i + count] == val and count < 6: count += 1
            if count >= 3: cl_tokens.append((16, count - 3)); i += count

    cl_freq = {i: 0 for i in range(19)}
    for t in cl_tokens: cl_freq[t[0]] += 1
    
    cl_len = build_huffman_lengths(cl_freq)
    cl_codes = assign_codes(cl_len)
    
    CL_ORDER = [16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15]
    hclen = 18
    while hclen >= 4 and cl_len.get(CL_ORDER[hclen], 0) == 0: hclen -= 1

    # Deflate ストリームへのビット書き込み
    class FastBitWriter:
        def __init__(self): self.val = 0; self.bits = 0; self.out = bytearray()
        def write(self, val, bits):
            self.val |= (val << self.bits); self.bits += bits
            while self.bits >= 8: self.out.append(self.val & 0xFF); self.val >>= 8; self.bits -= 8
        def flush(self):
            if self.bits > 0: self.out.append(self.val & 0xFF); self.val = 0; self.bits = 0
            return bytes(self.out)

    def rev_bits(val, length):
        res = 0
        for _ in range(length): res = (res << 1) | (val & 1); val >>= 1
        return res

    bw = FastBitWriter()
    bw.write(1, 1) # BFINAL
    bw.write(2, 2) # BTYPE
    bw.write((hlit + 1) - 257, 5) 
    bw.write((hdist + 1) - 1, 5)
    bw.write((hclen + 1) - 4, 4)

    for i in range(hclen + 1):
        bw.write(cl_len.get(CL_ORDER[i], 0), 3)

    for t in cl_tokens:
        sym = t[0]
        bw.write(rev_bits(cl_codes[sym], cl_len[sym]), cl_len[sym])
        if sym == 16: bw.write(t[1], 2)
        elif sym == 17: bw.write(t[1], 3)
        elif sym == 18: bw.write(t[1], 7)

    for t in encoded_tokens:
        if t[0] == 'lit':
            sym = t[1]
            bw.write(rev_bits(lit_codes[sym], lit_len[sym]), lit_len[sym])
        else:
            _, lsym, lext, lval, dsym, dext, dval = t
            bw.write(rev_bits(lit_codes[lsym], lit_len[lsym]), lit_len[lsym])
            if lext > 0: bw.write(lval, lext)
            bw.write(rev_bits(dist_codes[dsym], dist_len[dsym]), dist_len[dsym])
            if dext > 0: bw.write(dval, dext)

    deflate_data = bw.flush()
    zlib_stream = b'\x78\xda' + deflate_data + struct.pack('>I', adler)

    # PNG ファイル出力
    def write_chunk(f, chunk_type, data):
        f.write(struct.pack('>I', len(data)))
        f.write(chunk_type)
        f.write(data)
        f.write(struct.pack('>I', binascii.crc32(data, binascii.crc32(chunk_type)) & 0xffffffff))

    with open(filename, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        write_chunk(f, b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 2, 0, 0, 0))
        write_chunk(f, b'IDAT', zlib_stream)
        write_chunk(f, b'IEND', b'')
        
    print(f"PNG生成完了: {filename}")

if __name__ == "__main__":
    create_handwritten_png(WIDTH, HEIGHT, OUTPUT_FILENAME)
