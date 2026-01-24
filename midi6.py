import tkinter as tk
from tkinter import filedialog, messagebox, ttk, colorchooser
import mido
import cv2
import numpy as np
import subprocess
import os
import threading
import random
import bisect
import colorsys

# ==========================================
# 【重要】FluidSynthのパス設定
# ==========================================
# 環境変数PATHに通っていない場合はフルパスを指定してください
# 例: r"C:\Tools\fluidsynth\bin\fluidsynth.exe"
FLUIDSYNTH_CMD = "fluidsynth"

class MidiToVideoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal MIDI Renderer v3.1 (Debug Mode)")
        self.root.geometry("750x900")

        # --- 変数定義 ---
        self.midi_path = tk.StringVar()
        self.sf2_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.status_msg = tk.StringVar(value="準備完了")
        self.progress_val = tk.DoubleVar(value=0)
        
        self.force_default_sound = tk.BooleanVar(value=True)
        
        # 映像基本設定
        self.fps_var = tk.IntVar(value=30)
        self.width_var = tk.IntVar(value=1920)
        self.height_var = tk.IntVar(value=1080)
        self.time_window = tk.DoubleVar(value=4.0)

        # マージン設定
        self.margin_top = tk.IntVar(value=50)
        self.margin_bottom = tk.IntVar(value=50)
        self.margin_left = tk.IntVar(value=150) 
        self.margin_right = tk.IntVar(value=50)

        # レンダリングモード
        self.render_mode = tk.StringVar(value="Horizontal_RtoL") 
        
        # オプション
        self.show_piano = tk.BooleanVar(value=True)
        self.show_note_names = tk.BooleanVar(value=True)
        self.enable_velocity = tk.BooleanVar(value=True) # ベロシティによる濃淡
        self.pitch_range = tk.IntVar(value=2) # ピッチベンド幅(半音)

        # 色設定
        self.color_mode = tk.StringVar(value="Random") # Random, Single, Rainbow
        self.base_color_hex = tk.StringVar(value="#00FF00") # Singleモード用

        self.create_widgets()

    def create_widgets(self):
        # スクロール可能なメインエリア
        main_canvas = tk.Canvas(self.root)
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=main_canvas.yview)
        scrollable_frame = tk.Frame(main_canvas)

        scrollable_frame.bind("<Configure>", lambda e: main_canvas.configure(scrollregion=main_canvas.bbox("all")))
        main_canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        main_canvas.configure(yscrollcommand=scrollbar.set)
        main_canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        pad_opts = {'padx': 10, 'pady': 5}
        
        # 1. ファイル
        file_frame = tk.LabelFrame(scrollable_frame, text="ファイル選択", **pad_opts)
        file_frame.pack(fill=tk.X, **pad_opts)
        self.make_file_input(file_frame, "MIDIファイル:", self.midi_path, [("MIDI", "*.mid"), ("All", "*.*")], 0)
        self.make_file_input(file_frame, "SoundFont:", self.sf2_path, [("SoundFont", "*.sf2"), ("All", "*.*")], 1)
        self.make_file_input(file_frame, "保存先 (mp4):", self.output_path, [("MP4", "*.mp4")], 2, save=True)

        # 2. モード
        mode_frame = tk.LabelFrame(scrollable_frame, text="レンダリング方向", **pad_opts)
        mode_frame.pack(fill=tk.X, **pad_opts)
        modes = [
            ("横: 右から左 (標準)", "Horizontal_RtoL"),
            ("横: 左から右 (逆再生風)", "Horizontal_LtoR"),
            ("縦: 上から下 (Synthesia/落下)", "Vertical_Falling"),
            ("縦: 下から上 (音ゲー/上昇)", "Vertical_Rising"),
        ]
        for text, val in modes:
            tk.Radiobutton(mode_frame, text=text, variable=self.render_mode, value=val).pack(anchor="w", padx=10)

        # 3. ビジュアル設定 (色・効果)
        vis_frame = tk.LabelFrame(scrollable_frame, text="ビジュアル・色設定", **pad_opts)
        vis_frame.pack(fill=tk.X, **pad_opts)

        # カラーモード
        tk.Label(vis_frame, text="カラーモード:").grid(row=0, column=0, sticky="w")
        tk.OptionMenu(vis_frame, self.color_mode, "Random", "Single", "Rainbow").grid(row=0, column=1, sticky="w", padx=5)
        
        # 色選択ボタン
        btn_col = tk.Button(vis_frame, text="単色時の色を選択", command=self.pick_color)
        btn_col.grid(row=0, column=2, padx=10)
        self.lbl_col_preview = tk.Label(vis_frame, text="■", fg=self.base_color_hex.get(), font=("Arial", 16))
        self.lbl_col_preview.grid(row=0, column=3)

        # ベロシティ & ピッチベンド
        tk.Checkbutton(vis_frame, text="ベロシティを反映 (弱い音を暗くする)", variable=self.enable_velocity).grid(row=1, column=0, columnspan=2, sticky="w", pady=5)
        
        pb_frame = tk.Frame(vis_frame)
        pb_frame.grid(row=2, column=0, columnspan=4, sticky="w")
        tk.Label(pb_frame, text="ピッチベンド幅 (半音):").pack(side=tk.LEFT)
        tk.Entry(pb_frame, textvariable=self.pitch_range, width=5).pack(side=tk.LEFT, padx=5)

        # 4. サイズ・速度
        size_frame = tk.LabelFrame(scrollable_frame, text="解像度・速度", **pad_opts)
        size_frame.pack(fill=tk.X, **pad_opts)
        r1 = tk.Frame(size_frame)
        r1.pack(fill=tk.X)
        tk.Label(r1, text="幅:").pack(side=tk.LEFT); tk.Entry(r1, textvariable=self.width_var, width=5).pack(side=tk.LEFT, padx=2)
        tk.Label(r1, text="高さ:").pack(side=tk.LEFT); tk.Entry(r1, textvariable=self.height_var, width=5).pack(side=tk.LEFT, padx=2)
        tk.Label(r1, text="FPS:").pack(side=tk.LEFT); tk.Entry(r1, textvariable=self.fps_var, width=4).pack(side=tk.LEFT, padx=2)
        tk.Label(r1, text="表示秒数:").pack(side=tk.LEFT, padx=(10,0)); tk.Entry(r1, textvariable=self.time_window, width=4).pack(side=tk.LEFT, padx=2)

        # 5. 余白
        margin_frame = tk.LabelFrame(scrollable_frame, text="余白 (px) - 鍵盤エリア確保用", **pad_opts)
        margin_frame.pack(fill=tk.X, **pad_opts)
        r2 = tk.Frame(margin_frame)
        r2.pack(fill=tk.X)
        tk.Label(r2, text="上:").pack(side=tk.LEFT); tk.Entry(r2, textvariable=self.margin_top, width=5).pack(side=tk.LEFT)
        tk.Label(r2, text="下:").pack(side=tk.LEFT); tk.Entry(r2, textvariable=self.margin_bottom, width=5).pack(side=tk.LEFT)
        tk.Label(r2, text="左:").pack(side=tk.LEFT); tk.Entry(r2, textvariable=self.margin_left, width=5).pack(side=tk.LEFT)
        tk.Label(r2, text="右:").pack(side=tk.LEFT); tk.Entry(r2, textvariable=self.margin_right, width=5).pack(side=tk.LEFT)

        # 6. その他オプション
        opt_frame = tk.LabelFrame(scrollable_frame, text="表示オプション", **pad_opts)
        opt_frame.pack(fill=tk.X, **pad_opts)
        tk.Checkbutton(opt_frame, text="ピアノ鍵盤を表示", variable=self.show_piano).pack(anchor="w")
        tk.Checkbutton(opt_frame, text="音名を表示", variable=self.show_note_names).pack(anchor="w")
        tk.Checkbutton(opt_frame, text="楽器指定を無視 (全パートPiano化)", variable=self.force_default_sound).pack(anchor="w")

        # 実行ボタン
        btn_run = tk.Button(scrollable_frame, text="変換開始", command=self.start_conversion_thread, bg="#FF5722", fg="white", font=("Meiryo", 12, "bold"), height=2)
        btn_run.pack(fill=tk.X, pady=15, padx=10)

        self.pb = ttk.Progressbar(scrollable_frame, variable=self.progress_val, maximum=100)
        self.pb.pack(fill=tk.X, padx=10)
        self.lbl_status = tk.Label(scrollable_frame, textvariable=self.status_msg, anchor="w", fg="blue")
        self.lbl_status.pack(fill=tk.X, padx=10)

    def make_file_input(self, parent, label_text, var, filetypes, row, save=False):
        tk.Label(parent, text=label_text).grid(row=row, column=0, sticky="e")
        tk.Entry(parent, textvariable=var).grid(row=row, column=1, sticky="ew", padx=5)
        def select():
            if save: f = filedialog.asksaveasfilename(filetypes=filetypes, defaultextension=".mp4")
            else: f = filedialog.askopenfilename(filetypes=filetypes)
            if f: var.set(f)
        tk.Button(parent, text="参照", command=select).grid(row=row, column=2)
        parent.grid_columnconfigure(1, weight=1)

    def pick_color(self):
        c = colorchooser.askcolor(title="色を選択")[1]
        if c:
            self.base_color_hex.set(c)
            self.lbl_col_preview.config(fg=c)

    def start_conversion_thread(self):
        if not self.midi_path.get() or not self.sf2_path.get() or not self.output_path.get():
            messagebox.showerror("エラー", "ファイルパスが未指定です")
            return
        t = threading.Thread(target=self.run_conversion)
        t.start()

    def log(self, msg):
        self.status_msg.set(msg)
        print(msg)

    # --- ヘルパー関数: 色変換 ---
    def hex_to_bgr(self, hex_col):
        # tkinter(#RRGGBB) -> OpenCV(BGR)
        hex_col = hex_col.lstrip('#')
        rgb = tuple(int(hex_col[i:i+2], 16) for i in (0, 2, 4))
        return (rgb[2], rgb[1], rgb[0])

    def get_color_for_note(self, channel, note, velocity):
        # ベースカラー決定
        mode = self.color_mode.get()
        if mode == "Single":
            base_bgr = self.hex_to_bgr(self.base_color_hex.get())
        elif mode == "Rainbow":
            # 色相環: C=赤 -> B=紫 (note % 12)
            hue = (note % 12) / 12.0
            r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 1.0)
            base_bgr = (int(b*255), int(g*255), int(r*255))
        else: # Random (Channel based)
            # チャンネルごとの固定乱数シード
            random.seed(channel * 100)
            base_bgr = (random.randint(50,255), random.randint(50,255), random.randint(50,255))
        
        # ベロシティ適用 (明度調整)
        if self.enable_velocity.get():
            # 弱い音でも見えなくならないよう、最低輝度0.3くらいを確保
            factor = 0.3 + 0.7 * (velocity / 127.0)
            return (int(base_bgr[0]*factor), int(base_bgr[1]*factor), int(base_bgr[2]*factor))
        else:
            return base_bgr

    def create_sanitized_midi(self, input_path, output_path):
        mid = mido.MidiFile(input_path)
        new_mid = mido.MidiFile()
        new_mid.ticks_per_beat = mid.ticks_per_beat
        count = 0
        for track in mid.tracks:
            new_track = mido.MidiTrack()
            for msg in track:
                if msg.type == 'program_change': continue
                if msg.type == 'control_change' and msg.control in [0, 32]: continue
                if hasattr(msg, 'channel') and msg.channel == 9: msg.channel = 0
                if msg.type == 'note_on': count += 1
                new_track.append(msg)
            new_mid.tracks.append(new_track)
        new_mid.save(output_path)
        return count

    def run_conversion(self):
        try:
            original_midi = os.path.abspath(self.midi_path.get())
            sf2_file = os.path.abspath(self.sf2_path.get())
            output_file = os.path.abspath(self.output_path.get())
            
            temp_midi = "temp_x.mid"
            temp_wav = "temp_x.wav"
            temp_video = "temp_x.avi"

            target_midi = original_midi

            # MIDI前処理
            if self.force_default_sound.get():
                self.log("MIDI整形中...")
                cnt = self.create_sanitized_midi(original_midi, temp_midi)
                target_midi = temp_midi
                if cnt == 0: raise Exception("ノートがありません")

            # 音声生成
            self.log("音声レンダリング中 (FluidSynth)...")
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # --- 引数設定 ---
            # 指定通り: Gain=1.0, Polyphony=65536
            # ※ 65536は非常に大きいため、環境によってはクラッシュします。
            #    その場合は 4096 程度に下げてください。
            cmd_audio = [
                FLUIDSYNTH_CMD, 
                '-ni', 
                '-F', temp_wav, 
                '-r', '44100', 
                '-g', '1.0', 
                '-o', 'synth.polyphony=8192', 
                sf2_file, 
                target_midi
            ]

            # 実行＆エラーログ取得を強化
            proc = subprocess.run(cmd_audio, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)
            
            # 生成失敗の判定
            if proc.returncode != 0 or not os.path.exists(temp_wav) or os.path.getsize(temp_wav) < 1000:
                # エラーメッセージのデコード (WindowsではCP932/SJISが多い)
                try:
                    err_text = proc.stderr.decode('cp932')
                except:
                    err_text = proc.stderr.decode('utf-8', errors='ignore')
                
                # 詳細なエラーメッセージを作成
                detail = f"FluidSynth エラー (Exit Code: {proc.returncode})\n\n{err_text}"
                if not err_text.strip():
                    detail += "\n(エラーログが空でした。PATH設定やメモリ不足を確認してください)"
                
                raise Exception(detail)

            # 映像生成
            self.log("映像生成中 (ピッチベンド計算中)...")
            self.generate_video_v3(target_midi, temp_video)

            # 結合
            self.log("結合中 (FFmpeg)...")
            cmd_ffmpeg = [
                'ffmpeg', '-y', '-i', temp_video, '-i', temp_wav,
                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'fast',
                '-c:a', 'aac', '-b:a', '192k', '-shortest', output_file
            ]
            subprocess.run(cmd_ffmpeg, stdout=subprocess.PIPE, stderr=subprocess.PIPE, startupinfo=startupinfo)

            self.log(f"完了: {output_file}")
            messagebox.showinfo("成功", "変換完了！")

        except Exception as e:
            self.log("エラー発生")
            # エラーダイアログを表示
            messagebox.showerror("エラー詳細", str(e))
        finally:
            # 一時ファイル削除
            for f in [temp_midi, temp_wav, temp_video]:
                if os.path.exists(f): 
                    try: os.remove(f)
                    except: pass
            self.progress_val.set(0)

    # =========================================================================
    #  Rendering Logic v3.0 (Velocity & Pitch Bend)
    # =========================================================================
    def generate_video_v3(self, midi_path, video_out_path):
        W = self.width_var.get()
        H = self.height_var.get()
        fps = self.fps_var.get()
        mode = self.render_mode.get()
        
        m_top = self.margin_top.get()
        m_btm = self.margin_bottom.get()
        m_left = self.margin_left.get()
        m_right = self.margin_right.get()
        
        time_window = self.time_window.get()
        pitch_range_semitones = self.pitch_range.get()
        
        show_piano = self.show_piano.get()
        show_names = self.show_note_names.get()

        is_vertical = "Vertical" in mode
        is_reverse = "LtoR" in mode or "Rising" in mode

        mid = mido.MidiFile(midi_path)
        
        # 1. ピッチベンド情報の収集 (Time順にソート)
        bend_times = {}
        bend_values = {}
        # 初期値(0)を入れておく
        for ch in range(16):
            bend_times[ch] = [0.0]
            bend_values[ch] = [0.0]

        # 2. ノート情報の収集
        notes = []
        abs_time = 0.0
        active_notes = {} # (ch, note) -> {start, vel}
        
        min_note, max_note = 21, 108

        for msg in mid:
            abs_time += msg.time
            
            if msg.type == 'pitchwheel':
                val = (msg.pitch - 8192) / 8192.0 * pitch_range_semitones
                bend_times[msg.channel].append(abs_time)
                bend_values[msg.channel].append(val)

            elif msg.type == 'note_on' and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes[key] = {'start': abs_time, 'vel': msg.velocity}
                
            elif (msg.type == 'note_off') or (msg.type == 'note_on' and msg.velocity == 0):
                key = (msg.channel, msg.note)
                if key in active_notes:
                    d = active_notes.pop(key)
                    if min_note <= msg.note <= max_note:
                        # 色の計算
                        col = self.get_color_for_note(msg.channel, msg.note, d['vel'])
                        notes.append({
                            'note': msg.note,
                            'start': d['start'],
                            'end': abs_time,
                            'ch': msg.channel,
                            'vel': d['vel'],
                            'color': col
                        })
        
        duration = abs_time + 3.0
        total_frames = int(duration * fps)

        # 描画エリア計算
        draw_w = W - m_left - m_right
        draw_h = H - m_top - m_btm
        total_keys = max_note - min_note + 1
        
        if is_vertical:
            key_step = draw_w / total_keys
            px_per_sec = draw_h / time_window
            hit_line = (H - m_btm) if not is_reverse else m_top
        else:
            key_step = draw_h / total_keys
            px_per_sec = draw_w / time_window
            hit_line = m_left if not is_reverse else (W - m_right)

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(video_out_path, fourcc, fps, (W, H))

        # ピアノ用ユーティリティ
        def is_black(n): return (n % 12) in [1, 3, 6, 8, 10]
        def get_name(n): return ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"][n%12] + str(n//12-1)

        # --- フレームループ ---
        for f in range(total_frames):
            now = f / fps
            img = np.full((H, W, 3), (20, 20, 20), dtype=np.uint8)

            vis_min = now - time_window
            vis_max = now + time_window

            for n in notes:
                if n['end'] < vis_min or n['start'] > vis_max: continue
                
                # ポリゴン頂点計算
                step_dt = 0.05 
                t_points = np.arange(n['start'], n['end'] + 0.001, step_dt)
                if len(t_points) < 2: t_points = np.array([n['start'], n['end']])
                
                # ピッチベンド取得
                b_vals = np.interp(t_points, bend_times[n['ch']], bend_values[n['ch']])
                
                dt_arr = t_points - now
                base_idx = n['note'] - min_note
                
                if not is_vertical:
                    keys_arr = m_top + (max_note - (n['note'] + b_vals)) * key_step
                else:
                    keys_arr = m_left + (base_idx + b_vals) * key_step
                
                poly_pts = []
                k_thick = key_step + 1

                if is_vertical:
                    if not is_reverse: 
                        ys = hit_line - dt_arr * px_per_sec
                    else:
                        ys = hit_line + dt_arr * px_per_sec
                    
                    pts_L = np.column_stack((keys_arr, ys)).astype(np.int32)
                    pts_R = np.column_stack((keys_arr + k_thick, ys)).astype(np.int32)
                    poly_pts = np.vstack((pts_L, pts_R[::-1]))

                else:
                    if not is_reverse:
                        xs = hit_line + dt_arr * px_per_sec
                    else:
                        xs = hit_line - dt_arr * px_per_sec
                    
                    pts_T = np.column_stack((xs, keys_arr)).astype(np.int32)
                    pts_B = np.column_stack((xs, keys_arr + k_thick)).astype(np.int32)
                    poly_pts = np.vstack((pts_T, pts_B[::-1]))

                color = n['color']
                if n['start'] <= now < n['end']:
                    color = tuple([min(255, c + 150) for c in color])

                cv2.fillPoly(img, [poly_pts], color)

            # --- マージン処理 ---
            cv2.rectangle(img, (0,0), (W, m_top), (15,15,15), -1)
            cv2.rectangle(img, (0,H-m_btm), (W,H), (15,15,15), -1)
            cv2.rectangle(img, (0,0), (m_left,H), (15,15,15), -1)
            cv2.rectangle(img, (W-m_right,0), (W,H), (15,15,15), -1)

            # --- 判定線・鍵盤 ---
            line_pos = int(hit_line)
            if is_vertical:
                cv2.line(img, (0, line_pos), (W, line_pos), (200,200,200), 1)
                if show_piano:
                    kb_y = line_pos if not is_reverse else line_pos - m_top
                    kb_h = m_btm if not is_reverse else m_top
                    for i in range(total_keys):
                        note_num = min_note + i
                        kx = int(m_left + i * key_step)
                        kw = int(key_step) + 1
                        ib = is_black(note_num)
                        c = (40,40,40) if ib else (230,230,230)
                        cv2.rectangle(img, (kx, kb_y), (kx+kw, kb_y+kb_h), c, -1)
                        cv2.rectangle(img, (kx, kb_y), (kx+kw, kb_y+kb_h), (100,100,100), 1)
                        if show_names and not ib and (note_num%12==0):
                            cv2.putText(img, get_name(note_num), (kx, kb_y+kb_h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,0,0), 1)
            else:
                cv2.line(img, (line_pos, 0), (line_pos, H), (200,200,200), 1)
                if show_piano:
                    kb_x = 0 if not is_reverse else line_pos
                    kb_w = m_left if not is_reverse else m_right
                    for i in range(total_keys):
                        note_num = max_note - i
                        ky = int(m_top + i * key_step)
                        kh = int(key_step) + 1
                        ib = is_black(note_num)
                        c = (40,40,40) if ib else (230,230,230)
                        cv2.rectangle(img, (kb_x, ky), (kb_x+kb_w, ky+kh), c, -1)
                        cv2.rectangle(img, (kb_x, ky), (kb_x+kb_w, ky+kh), (100,100,100), 1)
                        if show_names and not ib and (note_num%12==0):
                            cv2.putText(img, get_name(note_num), (kb_x+5, ky+int(kh*0.7)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0,0,0), 1)

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