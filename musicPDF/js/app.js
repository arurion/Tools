document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("osmd-container");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const statusBar = document.getElementById("status-bar");

  // コントロール要素
  const formatSelect = document.getElementById("format-select");
  const measuresSelect = document.getElementById("measures-select");
  const densitySelect = document.getElementById("density-select");
  const scaleSlider = document.getElementById("scale-slider");
  const scaleLabel = document.getElementById("scale-label");
  const quantizeSelect = document.getElementById("quantize-select");

  const btnExportXml = document.getElementById("btn-export-xml");
  const btnDownloadPdf = document.getElementById("btn-download-pdf");
  const btnPrintSheet = document.getElementById("btn-print-sheet");

  let currentXmlContent = null;
  let currentFileName = "score";
  let lastLoadedFile = null;

  // 用紙サイズ定義（OSMDとjsPDFの両方で使用）
  const PAPER_FORMATS = {
    "A4_P": { isStandard: true,  osmdId: "A4_P",     width: 210,   height: 297,   jspdfFormat: "a4",     orientation: "portrait" },
    "A4_L": { isStandard: true,  osmdId: "A4_L",     width: 297,   height: 210,   jspdfFormat: "a4",     orientation: "landscape" },
    "B5_P": { isStandard: false, osmdId: "custom",   width: 182,   height: 257,   jspdfFormat: [182, 257], orientation: "portrait" },
    "B5_L": { isStandard: false, osmdId: "custom",   width: 257,   height: 182,   jspdfFormat: [257, 182], orientation: "landscape" },
    "Letter_P": { isStandard: true, osmdId: "Letter_P", width: 215.9, height: 279.4, jspdfFormat: "letter", orientation: "portrait" },
    "Letter_L": { isStandard: true, osmdId: "Letter_L", width: 279.4, height: 215.9, jspdfFormat: "letter", orientation: "landscape" },
    "A3_P": { isStandard: true,  osmdId: "A3_P",     width: 297,   height: 420,   jspdfFormat: "a3",     orientation: "portrait" },
    "A3_L": { isStandard: true,  osmdId: "A3_L",     width: 420,   height: 297,   jspdfFormat: "a3",     orientation: "landscape" }
  };

  // OSMDインスタンス初期化
  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
    autoResize: false, // 端末解像度による崩れを防ぎ、設定通りの出力を保証
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

  // レイアウト設定の反映と再描画
  function applyLayoutAndRender() {
    if (!osmd.sheet) return;

    // 1. 用紙サイズの設定
    const fmtKey = formatSelect.value;
    const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];
    if (formatSpec.isStandard) {
      osmd.setPageFormat(formatSpec.osmdId);
    } else {
      osmd.setCustomPageFormat(formatSpec.width, formatSpec.height);
    }

    // 2. 1段あたりの小節数 (0 = 自動)
    const measures = parseInt(measuresSelect.value, 10);
    osmd.EngravingRules.RenderXMeasuresPerLineAkaSystem = measures;

    // 3. 段間隔・密度設定
    const density = densitySelect.value;
    if (density === "compact") {
      osmd.EngravingRules.BetweenStaffDistance = 10;
      osmd.EngravingRules.StaffDistance = 5;
    } else if (density === "spacious") {
      osmd.EngravingRules.BetweenStaffDistance = 22;
      osmd.EngravingRules.StaffDistance = 9;
    } else {
      osmd.EngravingRules.BetweenStaffDistance = 15;
      osmd.EngravingRules.StaffDistance = 7;
    }

    // 4. ズーム・スケール
    const scale = parseFloat(scaleSlider.value);
    osmd.zoom = scale;

    osmd.render();
  }

  // ファイル解析処理
  async function handleFile(file) {
    if (!file) return;
    lastLoadedFile = file;
    currentFileName = file.name.replace(/\.[^/.]+$/, "");
    showStatus(`解析中: ${file.name}`);

    try {
      const ext = file.name.split('.').pop().toLowerCase();

      if (ext === 'mid' || ext === 'midi') {
        const buffer = await file.arrayBuffer();
        const parsedMidi = new Midi(buffer);
        currentXmlContent = Midi2Xml.convert(parsedMidi, {
          quantize: quantizeSelect.value
        });
        await osmd.load(currentXmlContent);

      } else if (ext === 'mxl') {
        const buffer = await file.arrayBuffer();
        await osmd.load(buffer);
        currentXmlContent = null;

      } else {
        let text = await file.text();
        text = text.replace(/<!DOCTYPE[\s\S]*?>/i, '');
        text = text.replace(/&(?!amp;|lt;|gt;|quot;|apos;|#\d+;|#x[0-9a-fA-F]+;)/g, '&amp;');
        currentXmlContent = text;

        try {
          await osmd.load(text);
        } catch (parseErr) {
          const buffer = await file.arrayBuffer();
          await osmd.load(buffer);
          currentXmlContent = null;
        }
      }

      applyLayoutAndRender();

      showStatus(`描画完了: ${file.name}`);
      btnExportXml.disabled = !currentXmlContent;
      btnDownloadPdf.disabled = false;
      btnPrintSheet.disabled = false;

    } catch (err) {
      console.error(err);
      showStatus(`読み込みエラー: ${err.message}`, true);
    }
  }

  // 指定用紙サイズで直接ベクターPDFを生成・ダウンロード
  async function downloadPdfDirectly() {
    const svgs = container.querySelectorAll("svg");
    if (svgs.length === 0) {
      showStatus("出力対象の楽譜が見つかりません。", true);
      return;
    }

    try {
      btnDownloadPdf.disabled = true;
      showStatus("PDFを生成中...");

      const fmtKey = formatSelect.value;
      const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];

      const { jsPDF } = window.jspdf;
      const pdf = new jsPDF({
        orientation: formatSpec.orientation,
        unit: "mm",
        format: formatSpec.jspdfFormat,
        compress: true
      });

      const pWidth = pdf.internal.pageSize.getWidth();
      const pHeight = pdf.internal.pageSize.getHeight();

      for (let i = 0; i < svgs.length; i++) {
        if (i > 0) {
          pdf.addPage(formatSpec.jspdfFormat, formatSpec.orientation);
        }
        showStatus(`PDFを生成中... (${i + 1} / ${svgs.length} ページ)`);

        const svg = svgs[i];
        await pdf.svg(svg, {
          x: 0,
          y: 0,
          width: pWidth,
          height: pHeight
        });
      }

      pdf.save(`${currentFileName}.pdf`);
      showStatus(`ダウンロード完了: ${currentFileName}.pdf (${fmtKey.replace('_', ' ')})`);

    } catch (err) {
      console.error(err);
      showStatus(`PDF生成エラー: ${err.message}`, true);
    } finally {
      btnDownloadPdf.disabled = false;
    }
  }

  // レイアウト変更イベント（即時再計算）
  formatSelect.addEventListener("change", applyLayoutAndRender);
  measuresSelect.addEventListener("change", applyLayoutAndRender);
  densitySelect.addEventListener("change", applyLayoutAndRender);

  scaleSlider.addEventListener("input", (e) => {
    scaleLabel.textContent = `${Math.round(e.target.value * 100)}%`;
  });
  scaleSlider.addEventListener("change", applyLayoutAndRender);

  quantizeSelect.addEventListener("change", () => {
    if (lastLoadedFile && lastLoadedFile.name.match(/\.midi?$/i)) {
      handleFile(lastLoadedFile);
    }
  });

  // ダウンロード・印刷
  btnDownloadPdf.addEventListener("click", downloadPdfDirectly);
  btnPrintSheet.addEventListener("click", () => window.print());

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

  // ドラッグ＆ドロップ & ファイルピッカー
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("dragover"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      handleFile(e.dataTransfer.files[0]);
    }
  });
  fileInput.addEventListener("change", (e) => {
    if (e.target.files.length > 0) {
      handleFile(e.target.files[0]);
    }
  });
});
