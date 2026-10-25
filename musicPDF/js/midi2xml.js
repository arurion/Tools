/**
 * ScoreFlow - MIDI to MusicXML Converter
 */
const Midi2Xml = (() => {
  const PITCH_CLASSES = ['C', 'C', 'D', 'D', 'E', 'F', 'F', 'G', 'G', 'A', 'A', 'B'];
  const ALTER_MAP = [0, 1, 0, 1, 0, 0, 1, 0, 1, 0, 1, 0];

  function durationToNoteType(durTicks, ppq) {
    const quarters = durTicks / ppq;
    if (quarters >= 3.5) return 'whole';
    if (quarters >= 1.75) return 'half';
    if (quarters >= 0.85) return 'quarter';
    if (quarters >= 0.4) return 'eighth';
    if (quarters >= 0.2) return '16th';
    return '32nd';
  }

  function convert(parsedMidi, options = {}) {
    const ppq = parsedMidi.header.ppq || 480;
    const quantizeDivision = parseInt(options.quantize || 16, 10);
    const gridTicks = Math.round((ppq * 4) / quantizeDivision);

    // 拍子の取得（未指定時は 4/4）
    let beats = 4;
    let beatType = 4;
    if (parsedMidi.header.timeSignatures && parsedMidi.header.timeSignatures.length > 0) {
      beats = parsedMidi.header.timeSignatures[0].timeSignature[0];
      beatType = parsedMidi.header.timeSignatures[0].timeSignature[1];
    }
    const ticksPerMeasure = Math.round(beats * (ppq * 4 / beatType));

    // 全トラックからノートを展開してクオンタイズ
    const allNotes = [];
    parsedMidi.tracks.forEach(track => {
      track.notes.forEach(note => {
        const start = Math.round(note.ticks / gridTicks) * gridTicks;
        const dur = Math.max(gridTicks, Math.round(note.durationTicks / gridTicks) * gridTicks);
        allNotes.push({
          midi: note.midi,
          startTick: start,
          endTick: start + dur,
          durationTicks: dur
        });
      });
    });

    if (allNotes.length === 0) {
      throw new Error("MIDI内に検出可能なノートイベントが存在しません。");
    }

    allNotes.sort((a, b) => a.startTick - b.startTick || a.midi - b.midi);

    // 音高の平均値からト音／ヘ音記号を自動選定
    const avgPitch = allNotes.reduce((sum, n) => sum + n.midi, 0) / allNotes.length;
    const isBass = avgPitch < 55;
    const clefSign = isBass ? 'F' : 'G';
    const clefLine = isBass ? '4' : '2';

    const maxTick = Math.max(...allNotes.map(n => n.endTick));
    const totalMeasures = Math.max(1, Math.ceil(maxTick / ticksPerMeasure));

    let xml = `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE score-partwise PUBLIC "-//Recordare//DTD MusicXML 3.1 Partwise//EN" "http://www.musicxml.org/dtds/partwise.dtd">
<score-partwise version="3.1">
  <work>
    <work-title>${parsedMidi.header.name || "Converted Score"}</work-title>
  </work>
  <part-list>
    <score-part id="P1">
      <part-name>Track</part-name>
    </score-part>
  </part-list>
  <part id="P1">
`;

    // 小節単位の構造化
    for (let m = 0; m < totalMeasures; m++) {
      const mStart = m * ticksPerMeasure;
      const mEnd = mStart + ticksPerMeasure;
      xml += `    <measure number="${m + 1}">\n`;

      if (m === 0) {
        xml += `      <attributes>
        <divisions>${ppq}</divisions>
        <key><fifths>0</fifths></key>
        <time><beats>${beats}</beats><beat-type>${beatType}</beat-type></time>
        <clef><sign>${clefSign}</sign><line>${clefLine}</line></clef>
      </attributes>\n`;
      }

      const measureNotes = allNotes.filter(n => n.startTick >= mStart && n.startTick < mEnd);

      if (measureNotes.length === 0) {
        xml += `      <note>
        <rest/>
        <duration>${ticksPerMeasure}</duration>
        <voice>1</voice>
        <type>whole</type>
      </note>\n`;
      } else {
        let cursor = mStart;
        for (let i = 0; i < measureNotes.length; i++) {
          const curNote = measureNotes[i];
          const isChord = i > 0 && curNote.startTick === measureNotes[i - 1].startTick;

          // 前の音符との空白を休符で埋める
          if (!isChord && curNote.startTick > cursor) {
            const restDur = curNote.startTick - cursor;
            xml += `      <note>
        <rest/>
        <duration>${restDur}</duration>
        <voice>1</voice>
        <type>${durationToNoteType(restDur, ppq)}</type>
      </note>\n`;
            cursor = curNote.startTick;
          }

          const effEnd = Math.min(mEnd, curNote.endTick);
          const dur = Math.max(gridTicks, effEnd - curNote.startTick);

          const step = PITCH_CLASSES[curNote.midi % 12];
          const alter = ALTER_MAP[curNote.midi % 12];
          const octave = Math.floor(curNote.midi / 12) - 1;

          xml += `      <note>
        ${isChord ? '<chord/>' : ''}
        <pitch>
          <step>${step}</step>
          ${alter !== 0 ? `<alter>${alter}</alter>` : ''}
          <octave>${octave}</octave>
        </pitch>
        <duration>${dur}</duration>
        <voice>1</voice>
        <type>${durationToNoteType(dur, ppq)}</type>
      </note>\n`;

          if (!isChord) {
            cursor = Math.max(cursor, effEnd);
          }
        }

        // 小節末尾の余白を休符で埋める
        if (cursor < mEnd) {
          const restDur = mEnd - cursor;
          xml += `      <note>
        <rest/>
        <duration>${restDur}</duration>
        <voice>1</voice>
        <type>${durationToNoteType(restDur, ppq)}</type>
      </note>\n`;
        }
      }

      xml += `    </measure>\n`;
    }

    xml += `  </part>\n</score-partwise>`;
    return xml;
  }

  return { convert };
})();
