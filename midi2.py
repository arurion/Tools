import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import mido
import cv2
import numpy as np
import subprocess
import os
import threading
import random

# ==========================================
# 【重要】FluidSynthのパス設定
# ==========================================
FLUIDSYNTH_CMD = "fluidsynth"
# パスが通っていない場合は以下のようにフルパスを書く
# FLUIDSYNTH_CMD = r"C:\Users\arurion\Downloads\...\bin\fluidsynth.exe"

class MidiToVideoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MIDI to Video (Force Sound Mode)")
        self.root.geometry("600x550")

        self.midi_path = tk.StringVar()
        self.sf2_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status_msg = tk.StringVar(value="準備完了")
        self.progress_val = tk.DoubleVar(value=0)
        
        # チェックボックス：楽器指定を無視するかどうか
        self.force_default_sound = tk.BooleanVar(value=True)

        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        self.make_file_input(frame, "MIDIファイル:", self.midi_path, [("MIDI files", "*.mid"), ("All files", "*.*")], 0)
        self.make_file_input(frame, "SoundFont (.sf2):", self.sf2_path, [("SoundFont", "*.sf2"), ("All files", "*.*")], 1)
        self.make_file_input(frame, "保存先 (mp4):", self.output_path, [("MP4 files", "*.mp4")], 2, save=True)

        # 設定エリア
        setting_frame = tk.LabelFrame(frame, text="設定", padx=10, pady=10)
        setting_frame.grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)

        tk.Label(setting_frame, text="FPS:").pack(side=tk.LEFT)
        self.fps_entry = tk.Entry(setting_frame, width=5)
        self.fps_entry.insert(0, "30")
        self.fps_entry.pack(side=tk.LEFT, padx=5)

        tk.Label(setting_frame, text="幅:").pack(side=tk.LEFT)
        self.width_entry = tk.Entry(setting_frame, width=6)
        self.width_entry.insert(0, "1280")
        self.width_entry.pack(side=tk.LEFT, padx=5)

        tk.Label(setting_frame, text="高さ:").pack(side=tk.LEFT)
        self.height_entry = tk.Entry(setting_frame, width=6)
        self.height_entry.insert(0, "720")
        self.height_entry.pack(side=tk.LEFT, padx=5)
        
        # チェックボックス追加
        chk = tk.Checkbutton(setting_frame, text="楽器指定を無視して強制再生", variable=self.force_default_sound)
        chk.pack(side=tk.LEFT, padx=15)

        btn_run = tk.Button(frame, text="変換開始", command=self.start_conversion_thread, bg="#dddddd", height=2)
        btn_run.grid(row=4, column=0, columnspan=3, sticky="ew", pady=10)

        pb = ttk.Progressbar(frame, variable=self.progress_val, maximum=100)
        pb.grid(row=5, column=0, columnspan=3, sticky="ew")

        lbl_status = tk.Label(frame, textvariable=self.status_msg, anchor="w")
        lbl_status.grid(row=6, column=0, columnspan=3, sticky="ew")

    def make_file_input(self, parent, label_text, var, filetypes, row, save=False):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="e")
        tk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=5)
        def select():
            if save: f = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=".mp4")
            else: f = filedialog.askopenfilename(filetypes=filetypes)
            if f: var.set(f)
        tk.Button(parent, text="参照", command=select).grid(row=row, column=2)
        parent.grid_columnconfigure(1, weight=1)

    def start_conversion_thread(self):
        if not self.midi_path.get() or not self.sf2_path.get() or not self.output_path.get():
            messagebox.showerror("エラー", "全てのファイルパスを指定してください。")
            return
        t = threading.Thread(target=self.run_conversion)
        t.start()

    def log(self, msg):
        self.status_msg.set(msg)
        print(msg)

    # MIDIファイルの楽器指定を削除する関数
    def create_sanitized_midi(self, input_path, output_path):
        mid = mido.MidiFile(input_path)
        new_mid = mido.MidiFile()
        new_mid.ticks_per_beat = mid.ticks_per_beat
        
        note_count = 0

        for track in mid.tracks:
            new_track = mido.MidiTrack()
            for msg in track:
                # Program Change (楽器指定) と Bank Select (CC#0, CC#32) を除外
                if msg.type == 'program_change':
                    continue
                if msg.type == 'control_change' and msg.control in [0, 32]:
                    continue
                
                # 念のためドラムチャンネル(ch9)も通常チャンネル(ch0)に変更してしまう
                # (Sine波フォントにドラムセットが入っていない場合用)
                if hasattr(msg, 'channel') and msg.channel == 9:
                    msg.channel = 0
                
                if msg.type == 'note_on':
                    note_count += 1
                    
                new_track.append(msg)
            new_mid.tracks.append(new_track)
        
        new_mid.save(output_path)
        return note_count

    def run_conversion(self):
        original_midi = os.path.abspath(self.midi_path.get())
        sf2_file = os.path.abspath(self.sf2_path.get())
        output_file = os.path.abspath(self.output_path.get())
        
        # 一時ファイル
        temp_midi = os.path.abspath("temp_processed.mid")
        temp_wav = os.path.abspath("temp_audio.wav")
        temp_video = os.path.abspath("temp_video.avi")

        # 使用するMIDIファイルを決定（加工するかどうか）
        target_midi = original_midi
        
        try:
            fps = int(self.fps_entry.get())
            width = int(self.width_entry.get())
            height = int(self.height_entry.get())

            # ---------------------------------------------------------
            # 0. MIDIの前処理 (楽器指定の無視)
            # ---------------------------------------------------------
            if self.force_default_sound.get():
                self.log("前処理: MIDIの楽器指定を削除中...")
                note_count = self.create_sanitized_midi(original_midi, temp_midi)
                target_midi = temp_midi
                self.log(f"ノート数: {note_count} (0ならMIDIが空です)")
                if note_count == 0:
                    messagebox.showwarning("警告", "MIDIファイルに音符が含まれていないようです。")

            # ---------------------------------------------------------
            # 1. MIDI -> WAV (FluidSynth)
            # ---------------------------------------------------------
            self.log("ステップ 1/3: 音声を生成中...")

            cmd_audio = [
                FLUIDSYNTH_CMD,
                '-ni',                 
                '-F', temp_wav,        
                '-r', '44100',         
                sf2_file,              
                target_midi            
            ]

            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            result = subprocess.run(
                cmd_audio, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE, 
                text=True, 
                encoding='utf-8', 
                errors='ignore',
                startupinfo=startupinfo
            )

            if not os.path.exists(temp_wav):
                raise Exception("WAVファイルの生成に失敗しました。")
            
            # WAVサイズチェック
            wav_size = os.path.getsize(temp_wav)
            self.log(f"生成WAVサイズ: {wav_size / 1024:.2f} KB")
            
            # 44バイト(ヘッダのみ)程度なら無音
            if wav_size < 1000:
                raise Exception(f"生成された音声が無音です(サイズ小)。\nFluidSynthエラーログ:\n{result.stderr[-500:]}")

            # ---------------------------------------------------------
            # 2. MIDI -> Video
            # ---------------------------------------------------------
            self.log("ステップ 2/3: 映像を生成中...")
            # 映像生成には元のMIDIを使ってもいいが、タイミング合わせのためターゲットを使う
            self.generate_piano_roll(target_midi, temp_video, width, height, fps)

            # ---------------------------------------------------------
            # 3. Combine (FFmpeg)
            # ---------------------------------------------------------
            self.log("ステップ 3/3: 結合中...")
            cmd_ffmpeg = [
                'ffmpeg', '-y',
                '-i', temp_video,
                '-i', temp_wav,
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '192k',
                '-shortest',
                output_file
            ]
            
            res_ffmpeg = subprocess.run(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='ignore', startupinfo=startupinfo)
            if res_ffmpeg.returncode != 0:
                 raise Exception(f"FFmpeg結合エラー:\n{res_ffmpeg.stderr[-500:]}")

            self.log(f"完了: {output_file}")
            messagebox.showinfo("成功", "変換が完了しました！")

        except Exception as e:
            self.log(f"エラー: {str(e)}")
            messagebox.showerror("エラー", str(e))
        finally:
            # 掃除
            if os.path.exists(temp_midi): os.remove(temp_midi)
            if os.path.exists(temp_wav): os.remove(temp_wav)
            if os.path.exists(temp_video): os.remove(temp_video)
            self.progress_val.set(0)

    def generate_piano_roll(self, midi_path, video_out_path, width, height, fps):
        mid = mido.MidiFile(midi_path)
        notes = [] 
        channel_colors = {}

        def get_channel_color(channel):
            if channel not in channel_colors:
                # 全てランダムカラーにする
                channel_colors[channel] = (random.randint(100, 255), random.randint(100, 255), random.randint(100, 255))
            return channel_colors[channel]

        abs_time = 0.0
        active_notes = {} 

        for msg in mid:
            abs_time += msg.time
            if msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes[key] = {'start': abs_time}
            elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes:
                    start_data = active_notes.pop(key)
                    notes.append({'note': msg.note, 'start': start_data['start'], 'end': abs_time, 'channel': msg.channel})
        
        duration = abs_time + 2.0
        # ノートが1つもない場合の対策
        if duration < 1.0: duration = 5.0
        
        total_frames = int(duration * fps)
        fourcc = cv2.VideoWriter_fourcc(*'MJPG')
        out = cv2.VideoWriter(video_out_path, fourcc, fps, (width, height))

        min_note, max_note = 21, 108
        key_height = height / (max_note - min_note + 1)
        time_window = 4.0 
        pixels_per_second = width / time_window
        playhead_x = int(width * 0.1)

        for f in range(total_frames):
            frame_time = f / fps
            img = np.full((height, width, 3), (30, 30, 30), dtype=np.uint8)
            cv2.line(img, (playhead_x, 0), (playhead_x, height), (255, 255, 255), 1)
            
            view_start = frame_time - (playhead_x / pixels_per_second)
            view_end = view_start + time_window

            for n in notes:
                if n['end'] < view_start or n['start'] > view_end: continue
                y = int((max_note - n['note']) * key_height)
                h = int(key_height) - 1
                if h < 1: h = 1
                x_s = int(playhead_x + (n['start'] - frame_time) * pixels_per_second)
                x_e = int(playhead_x + (n['end'] - frame_time) * pixels_per_second)
                
                color = get_channel_color(n['channel'])
                if n['start'] <= frame_time < n['end']: color = (255, 255, 255)
                cv2.rectangle(img, (x_s, y), (x_e, y + h), color, -1)

            out.write(img)
            prog = (f / total_frames) * 100
            if prog > self.progress_val.get() + 1:
                self.progress_val.set(prog)
                self.root.update_idletasks()
        out.release()

if __name__ == "__main__":
    root = tk.Tk()
    app = MidiToVideoApp(root)
    root.mainloop()