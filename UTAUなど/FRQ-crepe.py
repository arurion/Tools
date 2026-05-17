import os
import struct
import numpy as np
import soundfile as sf
import crepe  # CREPEライブラリ
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
        self.tool_name: bytes = b'CREPE Generator\x00'[:16]  # ツール名を追加（16バイト以内に収める）
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

def generate_frq_with_crepe(
    data: np.ndarray,
    sample_rate: int,
    per_samples: int = 256
) -> Frq:
    """CREPEアルゴリズムを使い、WAVデータからFRQデータを生成します。"""

    # 1. CREPEでF0推定（viterbi=Trueで滑らかな軌跡）
    time, f0, confidence, _ = crepe.predict(data, sample_rate, viterbi=True, step_size=per_samples / sample_rate * 1000)  # step_sizeをms単位で設定

    # 2. confidenceに基づき無声音部を0 Hzに設定（閾値: 0.5）
    f0 = np.where(confidence > 0.5, f0, 0.0)
    f0[f0 < 0] = 0.0  # 負値を0に設定（念のため）

    # 3. フレーム間隔の調整（CREPEのtimeに基づき補間）
    import scipy.interpolate as interp
    timestamps_original = np.arange(0, len(data) / sample_rate, per_samples / sample_rate)
    if len(time) > 1:  # 補間可能な場合
        interp_func = interp.interp1d(time, f0, kind='linear', fill_value=0.0, bounds_error=False)
        f0_interpolated = interp_func(timestamps_original)
    else:
        f0_interpolated = np.zeros_like(timestamps_original)

    # 4. 音量計算 (オリジナルデータを使用)
    num_frames = len(timestamps_original)
    amp = np.zeros(num_frames, dtype=np.float64)
    for i in range(num_frames):
        start_sample = i * per_samples
        end_sample = min(start_sample + per_samples, len(data))
        chunk = data[start_sample:end_sample]
        amp[i] = Frq.get_amp(chunk)

    # 5. Frqオブジェクトを作成
    frq_obj = Frq(frq=f0_interpolated, amp=amp, per_samples=per_samples)
    frq_obj.calc_average_frq()

    return frq_obj

class FrqGeneratorGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FRQ Generator with CREPE")
        self.root.geometry("400x200")

        self.label = tk.Label(self.root, text="ディレクトリを選択してFRQファイルを生成します。")
        self.label.pack(pady=10)

        self.select_button = tk.Button(self.root, text="ディレクトリを選択", command=self.select_directory)
        self.select_button.pack(pady=10)

        self.progress = ttk.Progressbar(self.root, orient="horizontal", length=300, mode="determinate")
        self.progress.pack(pady=10)

        self.status_label = tk.Label(self.root, text="")
        self.status_label.pack(pady=10)

        self.root.mainloop()

    def select_directory(self):
        directory = filedialog.askdirectory(title="ディレクトリを選択")
        if not directory:
            return

        wav_files = glob.glob(os.path.join(directory, "*.wav"))
        if not wav_files:
            messagebox.showinfo("情報", "ディレクトリ内にWAVファイルが見つかりませんでした。")
            return

        self.progress["maximum"] = len(wav_files)
        self.progress["value"] = 0
        self.status_label.config(text="処理中...")

        for i, wav_path in enumerate(wav_files):
            try:
                wav_data, fs = sf.read(wav_path, dtype='float64')
                if wav_data.ndim > 1:
                    wav_data = np.mean(wav_data, axis=1)

                frq_instance = generate_frq_with_crepe(wav_data, fs)
                frq_path = wav_path.replace(".wav", "_wav.frq").replace(".WAV", "_wav.frq")
                with open(frq_path, 'wb') as f:
                    f.write(frq_instance.output())

                self.progress["value"] = i + 1
                self.root.update_idletasks()
            except Exception as e:
                messagebox.showerror("エラー", f"ファイル {wav_path} の処理中にエラーが発生しました: {e}")

        self.status_label.config(text="処理完了")
        messagebox.showinfo("完了", "すべてのFRQファイルの生成が完了しました。")

if __name__ == '__main__':
    FrqGeneratorGUI()
