import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import mido
import subprocess
import os
import threading

# ==========================================
# 【重要】FluidSynthのパス設定
# ==========================================
# 環境変数PATHに通っていない場合は、ここをフルパスに書き換えてください
# 例: FLUIDSYNTH_CMD = r"C:\Tools\fluidsynth-x64\bin\fluidsynth.exe"
FLUIDSYNTH_CMD = "fluidsynth"

class MidiToAudioApp:
    def __init__(self, root):
        self.root = root
        self.root.title("MIDI to Audio Converter (FluidSynth GUI)")
        self.root.geometry("600x450")

        # --- 変数定義 ---
        self.midi_path = tk.StringVar()
        self.sf2_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status_msg = tk.StringVar(value="準備完了")
        self.progress_val = tk.DoubleVar(value=0)
        
        # 設定用変数
        self.gain_val = tk.DoubleVar(value=1.0)       # デフォルトGain 1.0
        self.polyphony_val = tk.IntVar(value=65536)   # デフォルト同時発音数 65536
        self.force_default_sound = tk.BooleanVar(value=True) # 全パートPiano化オプション

        self.create_widgets()

    def create_widgets(self):
        # メインフレーム
        main_frame = tk.Frame(self.root, padx=15, pady=15)
        main_frame.pack(fill=tk.BOTH, expand=True)

        pad_opts = {'padx': 5, 'pady': 5}
        
        # 1. ファイル選択エリア
        file_frame = tk.LabelFrame(main_frame, text="ファイル選択", **pad_opts)
        file_frame.pack(fill=tk.X, pady=10)
        
        self.make_file_input(file_frame, "MIDIファイル:", self.midi_path, [("MIDI", "*.mid"), ("All", "*.*")], 0)
        self.make_file_input(file_frame, "SoundFont:", self.sf2_path, [("SoundFont", "*.sf2"), ("All", "*.*")], 1)
        self.make_file_input(file_frame, "保存先 (WAV):", self.output_path, [("WAV Audio", "*.wav")], 2, save=True)

        # 2. 音声設定エリア
        set_frame = tk.LabelFrame(main_frame, text="音声合成設定 (FluidSynth)", **pad_opts)
        set_frame.pack(fill=tk.X, pady=10)

        # Gain
        r1 = tk.Frame(set_frame)
        r1.pack(fill=tk.X, pady=2)
        tk.Label(r1, text="Gain (音量):").pack(side=tk.LEFT)
        tk.Entry(r1, textvariable=self.gain_val, width=10).pack(side=tk.LEFT, padx=5)
        tk.Label(r1, text="(通常 0.2 ~ 5.0)").pack(side=tk.LEFT, padx=5, fg="gray")

        # Polyphony
        r2 = tk.Frame(set_frame)
        r2.pack(fill=tk.X, pady=2)
        tk.Label(r2, text="Polyphony (同時発音数):").pack(side=tk.LEFT)
        tk.Entry(r2, textvariable=self.polyphony_val, width=10).pack(side=tk.LEFT, padx=5)
        tk.Label(r2, text="(256 ~ 65536, クラッシュする場合は下げてください)").pack(side=tk.LEFT, padx=5, fg="gray")

        # オプション
        tk.Checkbutton(set_frame, text="楽器指定を無視する (全パートをSoundFontのデフォルト音色にする)", 
                       variable=self.force_default_sound).pack(anchor="w", pady=5)

        # 3. 実行ボタン
        btn_run = tk.Button(main_frame, text="WAV書き出し開始", command=self.start_conversion_thread, 
                            bg="#009688", fg="white", font=("Meiryo", 12, "bold"), height=2)
        btn_run.pack(fill=tk.X, pady=20)

        # 4. ステータス
        self.pb = ttk.Progressbar(main_frame, variable=self.progress_val, mode='indeterminate')
        self.pb.pack(fill=tk.X)
        
        self.lbl_status = tk.Label(main_frame, textvariable=self.status_msg, anchor="w", fg="blue")
        self.lbl_status.pack(fill=tk.X, pady=5)

    def make_file_input(self, parent, label_text, var, filetypes, row, save=False):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="e", padx=5, pady=2)
        tk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=5, pady=2)
        def select():
            if save: f = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=".wav")
            else: f = filedialog.askopenfilename(filetypes=filetypes)
            if f: var.set(f)
        tk.Button(parent, text="参照", command=select).grid(row=row, column=2, padx=5, pady=2)
        parent.grid_columnconfigure(1, weight=1)

    def start_conversion_thread(self):
        if not self.midi_path.get() or not self.sf2_path.get() or not self.output_path.get():
            messagebox.showerror("エラー", "ファイルパスがすべて指定されていません")
            return
        
        # UIロック風処理（簡易）
        self.pb.start(10)
        self.status_msg.set("処理中...")
        
        t = threading.Thread(target=self.run_conversion)
        t.start()

    def log(self, msg):
        self.status_msg.set(msg)
        print(msg)

    # MIDIの前処理（プログラムチェンジ除去など）
    def create_sanitized_midi(self, input_path, output_path):
        mid = mido.MidiFile(input_path)
        new_mid = mido.MidiFile()
        new_mid.ticks_per_beat = mid.ticks_per_beat
        
        has_notes = False
        for track in mid.tracks:
            new_track = mido.MidiTrack()
            for msg in track:
                # プログラムチェンジ（楽器変更）を削除
                if msg.type == 'program_change': continue
                # バンクセレクト等も削除した方が安全な場合が多い
                if msg.type == 'control_change' and msg.control in [0, 32]: continue
                # ドラムチャンネル(10ch=index 9)を通常チャンネル(1ch=index 0)に変更
                if hasattr(msg, 'channel') and msg.channel == 9: msg.channel = 0
                
                if msg.type == 'note_on': has_notes = True
                new_track.append(msg)
            new_mid.tracks.append(new_track)
        
        new_mid.save(output_path)
        return has_notes

    def run_conversion(self):
        temp_midi = None
        try:
            # パス取得
            script_dir = os.path.dirname(os.path.abspath(__file__))
            original_midi = os.path.abspath(self.midi_path.get())
            sf2_file = os.path.abspath(self.sf2_path.get())
            output_file = os.path.abspath(self.output_path.get())
            
            # 設定値取得
            gain = str(self.gain_val.get())
            poly = str(self.polyphony_val.get())
            
            target_midi = original_midi

            # MIDI前処理（必要な場合）
            if self.force_default_sound.get():
                self.log("MIDIデータを整形中...")
                temp_midi = os.path.join(script_dir, "temp_audio_gen.mid")
                has_notes = self.create_sanitized_midi(original_midi, temp_midi)
                if not has_notes:
                    raise Exception("MIDIファイルにノート情報が含まれていません")
                target_midi = temp_midi

            # FluidSynthコマンド実行
            self.log("WAV書き出し中 (FluidSynth)...")
            
            # Windowsで黒い画面が出ないようにする設定
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [
                FLUIDSYNTH_CMD,
                '-ni',                     # 非対話モード
                '-F', output_file,         # 出力先ファイル
                '-r', '44100',             # サンプリングレート
                '-g', gain,                # ゲイン
                '-o', f'synth.polyphony={poly}', # 同時発音数
                sf2_file,                  # SoundFont
                target_midi                # MIDIファイル
            ]

            # 実行
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)

            # 結果判定
            if proc.returncode != 0 or not os.path.exists(output_file) or os.path.getsize(output_file) < 1000:
                # エラーメッセージ取得
                try:
                    err_msg = proc.stderr.decode('cp932')
                except:
                    err_msg = proc.stderr.decode('utf-8', errors='ignore')
                
                raise Exception(f"FluidSynth エラー:\n{err_msg}")

            self.log(f"完了: {output_file}")
            messagebox.showinfo("成功", f"書き出しが完了しました！\n\n{output_file}")

        except Exception as e:
            self.log("エラー発生")
            messagebox.showerror("エラー", str(e))
        finally:
            self.pb.stop()
            # 一時ファイルがあれば削除
            if temp_midi and os.path.exists(temp_midi):
                try: os.remove(temp_midi)
                except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = MidiToAudioApp(root)
    root.mainloop()
