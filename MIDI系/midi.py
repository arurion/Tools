import tkinter as tk
from tkinter import filedialog, messagebox
import pretty_midi
import numpy as np
from scipy.io.wavfile import write as write_wav
import moviepy.editor as mpy
import subprocess
import os
from threading import Thread

class MidiToPianoRollVideo(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MIDI → ピアノロール動画変換ツール")
        self.geometry("500x320")
        self.resizable(False, False)

        tk.Label(self, text="MIDI → ピアノロール動画変換ツール", font=("メイリオ", 14, "bold")).pack(pady=10)

        self.midi_var = tk.StringVar()
        self.sf2_var = tk.StringVar()
        self.out_var = tk.StringVar()

        def add_row(text, var):
            frame = tk.Frame(self)
            frame.pack(fill="x", padx=20, pady=5)
            tk.Label(frame, text=text, width=12, anchor="w").pack(side="left")
            tk.Entry(frame, textvariable=var, width=40).pack(side="left", padx=5)
            return frame

        row1 = add_row("MIDIファイル", self.midi_var)
        tk.Button(row1, text="選択", command=self.select_midi).pack(side="right")

        row2 = add_row("SoundFont(.sf2)", self.sf2_var)
        tk.Button(row2, text="選択", command=self.select_sf2).pack(side="right")

        row3 = add_row("出力MP4", self.out_var)
        tk.Button(row3, text="選択", command=self.select_output).pack(side="right")

        tk.Button(self, text="変換開始", bg="#0066ff", fg="white", font=("メイリオ", 12, "bold"),
                  height=2, command=self.start_convert).pack(fill="x", padx=80, pady=20)

    def select_midi(self):
        path = filedialog.askopenfilename(filetypes=[("MIDIファイル", "*.mid *.midi")])
        if path: self.midi_var.set(path)

    def select_sf2(self):
        path = filedialog.askopenfilename(filetypes=[("SoundFont", "*.sf2 *.sf3")])
        if path: self.sf2_var.set(path)

    def select_output(self):
        path = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4動画", "*.mp4")])
        if path: self.out_var.set(path)

    def start_convert(self):
        if not all([self.midi_var.get(), self.sf2_var.get(), self.out_var.get()]):
            messagebox.showerror("エラー", "すべての項目を入力してください")
            return

        Thread(target=self.convert, daemon=True).start()

    def convert(self):
        midi_path = self.midi_var.get()
        sf2_path = self.sf2_var.get()
        output_path = self.out_var.get()

        try:
            # 1. PrettyMIDIで解析（内部でmido使用）
            pm = pretty_midi.PrettyMIDI(midi_path)

            # 2. fluidsynthコマンドで高品質WAV生成（python-fluidsynth不要）
            temp_wav = "temp_pianoroll_audio.wav"
            fs = 44100
            cmd = [
                "fluidsynth", "-ni", "-F", temp_wav, "-r", str(fs),
                sf2_path, midi_path
            ]
            subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 3. ノート情報収集（ドラム除外）
            notes = []
            colors = [(255, 100, 100), (100, 255, 100), (100, 100, 255),
                      (255, 255, 100), (255, 100, 255), (100, 255, 255)]
            color_idx = 0
            for inst in pm.instruments:
                if inst.is_drum:
                    continue
                color_base = colors[color_idx % len(colors)]
                color_idx += 1
                for note in inst.notes:
                    brightness = 0.6 + 0.4 * (note.velocity / 127)
                    color = tuple(int(c * brightness) for c in color_base)
                    notes.append({
                        "start": note.start,
                        "end": note.end,
                        "pitch": note.pitch,
                        "velocity": note.velocity,
                        "color": color
                    })

            duration = pm.get_end_time()

            # 4. 動画パラメータ
            width, height = 1920, 1080
            fps = 60
            pixel_per_sec = width / duration
            pixel_per_pitch = height / 128

            # 5. 背景（白鍵・黒鍵の階調）
            background = np.full((height, width, 3), 30, dtype=np.uint8)
            for p in range(128):
                y1 = int((127 - p) * pixel_per_pitch)
                y2 = int((127 - p + 1) * pixel_per_pitch)
                is_black = (p % 12) in {1, 3, 6, 8, 10}
                gray = 70 if is_black else 220
                background[y1:y2, :] = (gray, gray, gray)

            # 6. フレーム生成関数
            def make_frame(t):
                frame = background.copy()

                # 再生ヘッド
                x = int(t * pixel_per_sec)
                if 0 <= x < width:
                    frame[:, max(0, x-4):min(width, x+4)] = (255, 255, 255)

                # ノート描画
                for note in notes:
                    x1 = int(note["start"] * pixel_per_sec)
                    x2 = int(note["end"] * pixel_per_sec)
                    x1 = max(x1, 0)
                    x2 = min(x2, width)
                    if x1 >= x2:
                        continue

                    y1 = int((127 - note["pitch"]) * pixel_per_pitch)
                    y2 = int((127 - note["pitch"] + 1) * pixel_per_pitch)

                    color = note["color"]
                    frame[y1:y2, x1:x2] = color

                return frame

            # 7. 動画作成（moviepy → ffmpeg内部使用）
            video = mpy.VideoClip(make_frame, duration=duration)
            audio = mpy.AudioFileClip(temp_wav)
            final = video.set_audio(audio)
            final.write_videofile(
                output_path,
                fps=fps,
                codec="libx264",
                audio_codec="aac",
                threads=8,
                preset="medium",
                bitrate="8000k"
            )

            # 後処理
            os.remove(temp_wav)
            messagebox.showinfo("完了", f"変換が完了しました！\n{output_path}")

        except subprocess.CalledProcessError:
            messagebox.showerror("エラー", "fluidsynthコマンドが見つかりません。\nシステムにFluidSynthをインストールしてください。")
        except Exception as e:
            messagebox.showerror("エラー", f"変換失敗:\n{str(e)}")


if __name__ == "__main__":
    app = MidiToPianoRollVideo()
    app.mainloop()
