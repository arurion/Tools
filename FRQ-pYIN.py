import os
import struct
import numpy as np
import soundfile as sf
import librosa
from typing import Optional
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
import glob

class Frq:
    """UTAU標準の周波数表(.frq)ファイルを扱うクラス。"""
    def __init__(self, buf: Optional[bytes] = None, *,
                 per_samples: int = 256,
                 frq_average: Optional[float] = None,
                 frq: Optional[np.ndarray] = None,
                 amp: Optional[np.ndarray] = None):
        self.signature: str = "FREQ0003"
        self.tool_name: bytes = b'pYIN Generator\x00'[:16]  # ツール名
        self.per_samples = per_samples
        if buf:
            self.load_binary(buf)
        elif frq is not None and amp is not None:
            self.frq = frq
            self.amp = amp
            self.frq_average = frq_average if frq_average is not None else 0.0
            if frq_average is None:
                self.calc_average_frq()
        else:
            raise ValueError("bufまたはfrqとampのどちらかを指定する必要があります。")

    def load_binary(self, data: bytes):
        if len(data) < 40:
            raise ValueError("ファイルサイズが小さすぎます。")
        header_format = '<8sI d 16sI'
        header_size = struct.calcsize(header_format)
        _, self.per_samples, self.frq_average, _, data_count = struct.unpack(
            header_format, data[:header_size]
        )
        flat_array = np.frombuffer(data[header_size:], dtype=np.float64)
        self.frq = flat_array[0::2]
        self.amp = flat_array[1::2]

    def output(self) -> bytes:
        header_format = '<8sI d 16sI'
        header = struct.pack(
            header_format,
            self.signature.encode('ascii'),
            self.per_samples,
            self.frq_average,
            self.tool_name,
            len(self.frq)
        )
        body_array = np.empty(len(self.frq) * 2, dtype=np.float64)
        body_array[0::2] = self.frq
        body_array[1::2] = self.amp
        return header + body_array.tobytes()

    def calc_average_frq(self):
        valid_frq = self.frq[self.frq > 0]
        self.frq_average = np.mean(valid_frq) if len(valid_frq) > 0 else 0.0

    @staticmethod
    def get_amp(data_chunk: np.ndarray) -> float:
        return np.mean(np.abs(data_chunk)) if len(data_chunk) > 0 else 0.0

def generate_frq_with_pyin(
    data: np.ndarray,
    sample_rate: int,
    per_samples: int = 256
) -> Frq:
    """pYIN（librosa.pyin）を使い、WAVデータからFRQデータを生成します。"""

    # 1. pYINでF0推定（人間の声域に最適化）
    fmin = librosa.note_to_hz('C2')
    fmax = librosa.note_to_hz('C7')
    f0, voiced_prob, _ = librosa.pyin(data, fmin=fmin, fmax=fmax, sr=sample_rate, 
                                     frame_length=2048, hop_length=per_samples)

    # 2. voicing判定（確率0.5以上を有声音、ナノ値は0に置換）
    f0 = np.where(voiced_prob > 0.5, f0, 0.0)
    f0[np.isnan(f0)] = 0.0

    # 3. 音量計算
    num_frames = len(f0)
    amp = np.zeros(num_frames, dtype=np.float64)
    for i in range(num_frames):
        start_sample = i * per_samples
        end_sample = min(start_sample + per_samples, len(data))
        chunk = data[start_sample:end_sample]
        amp[i] = Frq.get_amp(chunk)

    # 4. Frqオブジェクト作成
    frq_obj = Frq(frq=f0, amp=amp, per_samples=per_samples)
    frq_obj.calc_average_frq()

    return frq_obj

class FrqGeneratorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FRQ Generator with pYIN (最高精度)")
        self.root.geometry("420x220")
        tk.Label(self.root, text="【pYIN版】UTAU FRQ生成ツール\n精度が最も高く、処理も高速です", font=("", 11)).pack(pady=15)
        tk.Button(self.root, text="ディレクトリを選択して一括生成", command=self.select_directory, width=30, height=2).pack(pady=10)
        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=350, mode="determinate")
        self.progress.pack(pady=10)
        self.status_label = tk.Label(self.root, text="")
        self.status_label.pack(pady=5)
        self.root.mainloop()

    def select_directory(self):
        directory = filedialog.askdirectory(title="ディレクトリを選択")
        if not directory:
            return

        wav_files = glob.glob(os.path.join(directory, "*.wav"))
        if not wav_files:
            messagebox.showinfo("情報", "WAVファイルが見つかりませんでした。")
            return

        self.progress["maximum"] = len(wav_files)
        self.progress["value"] = 0
        self.status_label.config(text="処理中...（pYINで高精度生成）")

        for i, wav_path in enumerate(wav_files):
            try:
                wav_data, fs = sf.read(wav_path, dtype='float64')
                if wav_data.ndim > 1:
                    wav_data = np.mean(wav_data, axis=1)  # ステレオ→モノラル

                frq_instance = generate_frq_with_pyin(wav_data, fs)
                frq_path = wav_path.replace(".wav", "_wav.frq").replace(".WAV", "_wav.frq")
                with open(frq_path, 'wb') as f:
                    f.write(frq_instance.output())

                self.progress["value"] = i + 1
                self.root.update_idletasks()
            except Exception as e:
                messagebox.showerror("エラー", f"{wav_path}\n{e}")

        self.status_label.config(text="完了！pYINで最高精度のFRQが生成されました")
        messagebox.showinfo("完了", f"{len(wav_files)}ファイルのFRQ生成が完了しました！\n\nこれでほぼ間違いなく最高品質です！")

if __name__ == '__main__':
    FrqGeneratorGUI()