import os
import sys
import json
import math
import uuid
import argparse
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional

# ==========================================
# 定数 (VOICEVOX / UTAU 規格)
# ==========================================
TPQN = 480
DEFAULT_BPM = 120.0
FRAME_RATE = 93.75  # VOICEVOX 内部フレームレート
FRAME_PERIOD = 1.0 / FRAME_RATE
VALUE_INDICATING_NO_DATA = -1.0
DEFAULT_ENGINE_ID = "074fc39e-678b-4c13-8916-ffca8d505d1d"
DEFAULT_STYLE_ID = 3000


# ==========================================
# データ構造
# ==========================================
@dataclass
class Mode1:
    pb_type: str = "5"
    pitches: List[int] = field(default_factory=list)
    pb_start: float = 0.0


@dataclass
class Mode2:
    pbs: Tuple[float, float] = (0.0, 0.0)  # (PosMs, PitchShift_10cent)
    pbw: List[float] = field(default_factory=list)
    pby: List[float] = field(default_factory=list)
    pbm: List[str] = field(default_factory=list)
    vbr: List[float] = field(default_factory=list)


@dataclass
class TempoEvent:
    position_tick: int
    bpm: float


@dataclass
class Note:
    lyric: str = ""
    length: int = 480
    note_num: int = 60
    tempo: Optional[float] = None
    bpm: float = DEFAULT_BPM

    has_mode1: bool = False
    has_mode2: bool = False
    mode1: Mode1 = field(default_factory=Mode1)
    mode2: Mode2 = field(default_factory=Mode2)

    start_tick: int = 0
    end_tick: int = 0
    start_sec: float = 0.0
    end_sec: float = 0.0

    @property
    def is_rest(self) -> bool:
        return self.lyric.strip().lower() == "r"


# ==========================================
# UST パーサー (UST仕様準拠)
# ==========================================
class UstParser:
    @staticmethod
    def detect_encoding(file_path: str) -> str:
        """USTヘッダーの Charset= 指定を確認（未指定時はShift_JIS互換）"""
        try:
            with open(file_path, "r", encoding="latin-1") as f:
                for _ in range(15):
                    line = f.readline()
                    if not line:
                        break
                    line = line.strip()
                    if line.startswith("Charset="):
                        return line.split("=", 1)[1].strip()
        except Exception:
            pass
        return "cp932"

    @classmethod
    def parse(cls, file_path: str) -> Tuple[List[Note], float, List[TempoEvent]]:
        encoding = cls.detect_encoding(file_path)
        try:
            with open(file_path, "r", encoding=encoding) as f:
                lines = f.readlines()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

        blocks: List[Dict[str, str]] = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                if line == "[#TRACKEND]":
                    break
                blocks.append({"_header": line[1:-1]})
            elif "=" in line and blocks:
                k, v = line.split("=", 1)
                blocks[-1][k.strip()] = v.strip()

        # [#SETTING] のグローバルテンポ取得
        global_bpm = DEFAULT_BPM
        for b in blocks:
            if b.get("_header") == "#SETTING" and "Tempo" in b:
                try:
                    global_bpm = float(b["Tempo"])
                except ValueError:
                    pass
                break

        notes: List[Note] = []
        tempo_events: List[TempoEvent] = [TempoEvent(0, global_bpm)]
        accum_tick = 0

        for b in blocks:
            if not b.get("_header", "").startswith("#") or b.get("_header") in (
                "#SETTING",
                "#VERSION",
            ):
                continue
            if "Length" not in b and "Lyric" not in b:
                continue

            note = cls._parse_note_block(b)
            note.start_tick = accum_tick
            note.end_tick = accum_tick + note.length
            accum_tick += note.length

            if note.tempo is not None and note.tempo > 0:
                tempo_events.append(TempoEvent(note.start_tick, note.tempo))

            notes.append(note)

        return notes, global_bpm, tempo_events

    @classmethod
    def _parse_note_block(cls, d: Dict[str, str]) -> Note:
        note = Note()

        raw_lyric = d.get("Lyric", "R")
        if raw_lyric.startswith("?"):
            raw_lyric = raw_lyric[1:]
        note.lyric = raw_lyric

        note.length = int(d.get("Length", 480))
        note.note_num = int(d.get("NoteNum", 60))

        if "Tempo" in d:
            try:
                note.tempo = float(d["Tempo"])
            except ValueError:
                pass

        # --- Mode1 解析 ---
        pb_str = d.get("PitchBend") or d.get("Pitches") or d.get("Piches")
        if "PBType" in d or pb_str:
            note.has_mode1 = True
            note.mode1.pb_type = d.get("PBType", "5")
            if pb_str:
                note.mode1.pitches = [
                    int(p.strip()) if p.strip() else 0 for p in pb_str.split(",")
                ]
            note.mode1.pb_start = float(d.get("PBStart", 0.0))

        # --- Mode2 解析 ---
        if "PBS" in d:
            pbs_str = d["PBS"]
            parts = pbs_str.split(";") if ";" in pbs_str else pbs_str.split(",")
            try:
                pbs_x = float(parts[0]) if len(parts) >= 1 and parts[0].strip() else 0.0
                pbs_y = float(parts[1]) if len(parts) >= 2 and parts[1].strip() else 0.0
            except ValueError:
                pbs_x, pbs_y = 0.0, 0.0

            w_list: List[float] = []
            y_list: List[float] = []
            if "PBW" in d and d["PBW"].strip():
                for s in d["PBW"].split(","):
                    try:
                        w_list.append(float(s) if s.strip() else 0.0)
                    except ValueError:
                        w_list.append(0.0)

            if "PBY" in d and d["PBY"].strip():
                for s in d["PBY"].split(","):
                    try:
                        y_list.append(float(s) if s.strip() else 0.0)
                    except ValueError:
                        y_list.append(0.0)

            if len(w_list) > 0:
                while len(y_list) < len(w_list):
                    y_list.append(0.0)

                note.has_mode2 = True
                note.mode2.pbs = (pbs_x, pbs_y)
                note.mode2.pbw = w_list
                note.mode2.pby = y_list
                if "PBM" in d:
                    note.mode2.pbm = [x.strip() for x in d["PBM"].split(",")]

            if "VBR" in d and d["VBR"].strip():
                vbr_parts = d["VBR"].split(",")
                v_vals = []
                for x in vbr_parts[:7]:
                    try:
                        v_vals.append(float(x) if x.strip() else 0.0)
                    except ValueError:
                        v_vals.append(0.0)
                note.mode2.vbr = v_vals

        return note


# ==========================================
# 時間・ピッチ補間計算エンジン
# ==========================================
class PitchCalculator:
    @staticmethod
    def calculate_timing(notes: List[Note], initial_bpm: float):
        current_bpm = initial_bpm
        current_sec = 0.0

        for note in notes:
            if note.tempo is not None and note.tempo > 0:
                current_bpm = note.tempo
            note.bpm = current_bpm

            duration_sec = note.length * (60.0 / (current_bpm * TPQN))
            note.start_sec = current_sec
            note.end_sec = current_sec + duration_sec
            current_sec += duration_sec

    @staticmethod
    def interpolate(t: float, x0: float, y0: float, x1: float, y1: float, mode: str) -> float:
        if x1 <= x0:
            return y0
        ratio = max(0.0, min(1.0, (t - x0) / (x1 - x0)))
        if mode == "s":
            val = ratio
        elif mode == "j":
            val = ratio * ratio
        elif mode == "r":
            val = 1.0 - (1.0 - ratio) * (1.0 - ratio)
        else:
            val = (1.0 - math.cos(ratio * math.pi)) / 2.0
        return y0 + (y1 - y0) * val

    @classmethod
    def calculate_vibrato(cls, t_rel_ms: float, note_dur_ms: float, vbr: List[float]) -> float:
        if len(vbr) < 3 or vbr[0] <= 0:
            return 0.0

        v_len_pct, v_period, v_depth_cent = vbr[0], vbr[1], vbr[2]
        v_fi_pct = vbr[3] if len(vbr) > 3 else 0.0
        v_fo_pct = vbr[4] if len(vbr) > 4 else 0.0
        v_phase_pct = vbr[5] if len(vbr) > 5 else 0.0
        v_shift_pct = vbr[6] if len(vbr) > 6 else 0.0

        vib_len_ms = note_dur_ms * (v_len_pct / 100.0)
        vib_start_ms = note_dur_ms - vib_len_ms
        if t_rel_ms < vib_start_ms:
            return 0.0

        t_vib = t_rel_ms - vib_start_ms
        amp = 1.0

        fi_time = vib_len_ms * (v_fi_pct / 100.0)
        fo_time = vib_len_ms * (v_fo_pct / 100.0)
        if fi_time > 0 and t_vib < fi_time:
            amp *= t_vib / fi_time
        time_left = vib_len_ms - t_vib
        if fo_time > 0 and time_left < fo_time:
            amp *= max(0.0, time_left) / fo_time

        if v_period > 0:
            phase = 2 * math.pi * (v_phase_pct / 100.0)
            shift = v_depth_cent * (v_shift_pct / 100.0)
            sine = math.sin(2 * math.pi * (t_vib / v_period) - phase)
            return (sine * v_depth_cent + shift) * amp

        return 0.0

    @classmethod
    def generate_pitch_curve(cls, notes: List[Note]) -> List[float]:
        if not notes:
            return []

        total_duration = notes[-1].end_sec + 2.0
        total_frames = int(math.ceil(total_duration * FRAME_RATE))
        pitch_data = [VALUE_INDICATING_NO_DATA] * total_frames

        for note in notes:
            if note.is_rest:
                continue

            note_dur_ms = (note.end_sec - note.start_sec) * 1000.0

            # ---------------- Mode2 (ポルタメント) ----------------
            if note.has_mode2:
                pbs_time, pbs_pitch_10c = note.mode2.pbs
                control_points = [(pbs_time, pbs_pitch_10c * 10.0, "")]

                t_accum = pbs_time
                for i in range(len(note.mode2.pbw)):
                    w = note.mode2.pbw[i]
                    y_10c = note.mode2.pby[i]
                    m = note.mode2.pbm[i] if i < len(note.mode2.pbm) else ""
                    t_accum += w
                    control_points.append((t_accum, y_10c * 10.0, m))

                start_sec = note.start_sec + (pbs_time / 1000.0)
                last_pt_ms = control_points[-1][0] if control_points else 0.0
                end_sec = max(note.end_sec, note.start_sec + (last_pt_ms / 1000.0))

                start_f = max(0, int(start_sec * FRAME_RATE))
                end_f = min(total_frames, int(end_sec * FRAME_RATE) + 1)

                for f in range(start_f, end_f):
                    t_rel_ms = (f * FRAME_PERIOD - note.start_sec) * 1000.0
                    if t_rel_ms < pbs_time:
                        continue

                    if len(control_points) == 1 or t_rel_ms >= control_points[-1][0]:
                        offset_cent = control_points[-1][1]
                    else:
                        offset_cent = 0.0
                        for i in range(len(control_points) - 1):
                            x0, y0, _ = control_points[i]
                            x1, y1, mode = control_points[i + 1]
                            if x0 <= t_rel_ms <= x1:
                                offset_cent = cls.interpolate(t_rel_ms, x0, y0, x1, y1, mode)
                                break

                    offset_cent += cls.calculate_vibrato(t_rel_ms, note_dur_ms, note.mode2.vbr)

                    target_note = note.note_num + (offset_cent / 100.0)
                    hz = 440.0 * (2.0 ** ((target_note - 69.0) / 12.0))
                    if hz > 0:
                        pitch_data[f] = hz

            # ---------------- Mode1 (旧ピッチベンド) ----------------
            elif note.has_mode1 and note.mode1.pitches:
                pitches = note.mode1.pitches
                pb_start_ms = note.mode1.pb_start
                step_ms = 5.0 * (60000.0 / (note.bpm * TPQN))

                start_sec = note.start_sec + (pb_start_ms / 1000.0)
                end_sec = start_sec + (len(pitches) * step_ms / 1000.0)

                start_f = max(0, int(start_sec * FRAME_RATE))
                end_f = min(total_frames, int(end_sec * FRAME_RATE) + 1)

                for f in range(start_f, end_f):
                    t_rel_ms = ((f * FRAME_PERIOD - note.start_sec) * 1000.0) - pb_start_ms
                    if t_rel_ms < 0:
                        continue

                    idx = int(t_rel_ms / step_ms)
                    if idx < 0:
                        p_cent = float(pitches[0])
                    elif idx >= len(pitches) - 1:
                        p_cent = float(pitches[-1])
                    else:
                        x0 = idx * step_ms
                        x1 = (idx + 1) * step_ms
                        p_cent = cls.interpolate(t_rel_ms, x0, float(pitches[idx]), x1, float(pitches[idx + 1]), "s")

                    target_note = note.note_num + (p_cent / 100.0)
                    hz = 440.0 * (2.0 ** ((target_note - 69.0) / 12.0))
                    if hz > 0:
                        pitch_data[f] = hz

        return pitch_data


# ==========================================
# メイン処理 (VVPROJ 生成)
# ==========================================
def convert_ust_to_vvproj(ust_path: str, output_path: str, import_pitch: bool = True):
    print(f"[1/4] Parsing UST: {ust_path}")
    notes, initial_bpm, tempo_events = UstParser.parse(ust_path)
    if not notes:
        print("Error: No notes found.")
        return

    print("[2/4] Calculating timing...")
    PitchCalculator.calculate_timing(notes, initial_bpm)

    vv_notes = [
        {
            "id": str(uuid.uuid4()),
            "position": n.start_tick,
            "duration": n.length,
            "noteNumber": n.note_num,
            "lyric": n.lyric,
        }
        for n in notes
        if not n.is_rest
    ]

    # ピッチ曲線の生成（無効化オプション対応）
    if import_pitch:
        print("[3/4] Generating pitch curves...")
        pitch_edit_data = PitchCalculator.generate_pitch_curve(notes)
    else:
        print("[3/4] Skipping pitch curve generation (--no-pitch specified)...")
        pitch_edit_data = []

    tempos = [{"position": t.position_tick, "bpm": t.bpm} for t in tempo_events]

    track_id = str(uuid.uuid4())
    vvproj = {
        "appVersion": "0.25.1",
        "talk": {"audioKeys": [], "audioItems": {}},
        "song": {
            "tpqn": TPQN,
            "tempos": tempos,
            "timeSignatures": [{"measureNumber": 1, "beats": 4, "beatType": 4}],
            "tracks": {
                track_id: {
                    "name": "Imported UST",
                    "singer": {
                        "engineId": DEFAULT_ENGINE_ID,
                        "styleId": DEFAULT_STYLE_ID,
                    },
                    "keyRangeAdjustment": 0,
                    "volumeRangeAdjustment": 0,
                    "notes": vv_notes,
                    "pitchEditData": pitch_edit_data,
                    "volumeEditData": [],
                    "phonemeTimingEditData": {},
                    "solo": False,
                    "mute": False,
                    "gain": 1.0,
                    "pan": 0.0,
                }
            },
            "trackOrder": [track_id],
        },
    }

    print(f"[4/4] Writing VVPROJ: {output_path}")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(vvproj, f, ensure_ascii=False)
    print("Conversion completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert UTAU project file (.ust) to VOICEVOX project file (.vvproj)"
    )
    parser.add_argument("input_ust", help="Input .ust file path")
    parser.add_argument(
        "output_vvproj",
        nargs="?",
        default=None,
        help="Output .vvproj file path (default: same name as input file)",
    )
    parser.add_argument(
        "--no-pitch",
        action="store_true",
        help="Disable pitch curve import (VOICEVOX will automatically generate pitch)",
    )

    args = parser.parse_args()

    in_file = args.input_ust
    out_file = (
        args.output_vvproj
        if args.output_vvproj
        else os.path.splitext(in_file)[0] + ".vvproj"
    )

    convert_ust_to_vvproj(in_file, out_file, import_pitch=not args.no_pitch)
