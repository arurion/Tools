document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("osmd-container");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const statusBar = document.getElementById("status-bar");
  const zoomSelect = document.getElementById("zoom-select");
  const quantizeSelect = document.getElementById("quantize-select");
  const btnExportXml = document.getElementById("btn-export-xml");
  const btnPrintPdf = document.getElementById("btn-print-pdf");

  let currentXmlContent = null;
  let currentFileName = "score";
  let lastLoadedFile = null;

  // OpenSheetMusicDisplay の初期化 (A4縦・SVGベクターモード)
  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
    autoResize: true,
    backend: "svg",
    drawingParameters: "default",
    drawTitle: true,
    pageFormat: "A4_P",
    pageBackgroundColor: "#ffffff"
  });

  function showStatus(message, isError = false) {
    statusBar.style.display = "block";
    statusBar.textContent = message;
    statusBar.style.color = isError ? "#b91c1c" : "#334155";
    statusBar.style.borderLeftColor = isError ? "#ef4444" : "var(--accent-blue)";
  }

  async function handleFile(file) {
    if (!file) return;
    lastLoadedFile = file;
    currentFileName = file.name.replace(/\.[^/.]+$/, "");
    showStatus(`読み込み・解析中: ${file.name}`);

    try {
      const ext = file.name.split('.').pop().toLowerCase();

      if (ext === 'mid' || ext === 'midi') {
        // --- 1. MIDIファイル ---
        const buffer = await file.arrayBuffer();
        const parsedMidi = new Midi(buffer);
        currentXmlContent = Midi2Xml.convert(parsedMidi, {
          quantize: quantizeSelect.value
        });
        await osmd.load(currentXmlContent);

      } else if (ext === 'mxl') {
        // --- 2. 圧縮MusicXML (.mxl) ---
        const buffer = await file.arrayBuffer();
        await osmd.load(buffer);
        currentXmlContent = null;

      } else {
        // --- 3. MusicXML 4.0 / 3.x / 一般XML ---
        let text = await file.text();

        // MusicXML 4.0 対策: 外部DTD取得によるCORSエラーを防ぐためDOCTYPEを除去
        text = text.replace(/<!DOCTYPE[\s\S]*?>/i, '');

        // 未定義エンティティを安全にエスケープ
        text = text.replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;');

        currentXmlContent = text;

        try {
          await osmd.load(text);
        } catch (parseErr) {
          // 拡張子が .musicxml なのに実態が zip (.mxl) だった場合の自動フォールバック
          const buffer = await file.arrayBuffer();
          await osmd.load(buffer);
          currentXmlContent = null;
        }
      }

      osmd.zoom = parseFloat(zoomSelect.value);
      osmd.render();

      showStatus(`描画完了: ${file.name} （PDF出力の準備が整いました）`);
      btnExportXml.disabled = !currentXmlContent;
      btnPrintPdf.disabled = false;
    } catch (err) {
      console.error(err);
      showStatus(`読み込みエラー: ${err.message}`, true);
    }
  }

  // ドラッグ＆ドロップ
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });

  // ファイルダイアログ選択
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });

  // ズーム変更
  zoomSelect.addEventListener("change", () => {
    osmd.zoom = parseFloat(zoomSelect.value);
    osmd.render();
  });

  // クオンタイズ変更 (MIDIの場合のみ自動再解析)
  quantizeSelect.addEventListener("change", () => {
    if (lastLoadedFile && lastLoadedFile.name.match(/\.midi?$/i)) {
      handleFile(lastLoadedFile);
    }
  });

  // MusicXML保存
  btnExportXml.addEventListener("click", () => {
    if (!currentXmlContent) return;
    const blob = new Blob([currentXmlContent], { type: "application/vnd.recordare.musicxml+xml" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${currentFileName}.musicxml`;
    link.click();
    URL.revokeObjectURL(link);
  });

  // PDF出力 / 印刷
  btnPrintPdf.addEventListener("click", () => {
    // ブラウザの印刷ダイアログをトリガー（送信先: 「PDFに保存」を選択）
    window.print();
  });
});
