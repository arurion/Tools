document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("osmd-container");
  const dropZone = document.getElementById("drop-zone");
  const fileInput = document.getElementById("file-input");
  const statusBar = document.getElementById("status-bar");

  const formatSelect = document.getElementById("format-select");
  const measuresSelect = document.getElementById("measures-select");
  const scaleSlider = document.getElementById("scale-slider");
  const scaleLabel = document.getElementById("scale-label");
  const quantizeSelect = document.getElementById("quantize-select");

  const btnExportXml = document.getElementById("btn-export-xml");
  const btnDownloadPdf = document.getElementById("btn-download-pdf");
  const btnPrintSheet = document.getElementById("btn-print-sheet");

  let currentXmlContent = null;
  let currentFileName = "score";
  let lastLoadedFile = null;

  // 用紙規格設定: VexFlowが必要とする十分な最小キャンバス幅（px）を確保
  const PAPER_FORMATS = {
    "A4_P":     { osmdOption: "A4_P",     widthMm: 210,   heightMm: 297,   canvasWidthPx: 1050 },
    "A4_L":     { osmdOption: "A4_L",     widthMm: 297,   heightMm: 210,   canvasWidthPx: 1480 },
    "Letter_P": { osmdOption: "Letter_P", widthMm: 215.9, heightMm: 279.4, canvasWidthPx: 1080 },
    "Letter_L": { osmdOption: "Letter_L", widthMm: 279.4, heightMm: 215.9, canvasWidthPx: 1400 },
    "Endless":  { osmdOption: "Endless",  widthMm: 210,   heightMm: 297,   canvasWidthPx: 1050 }
  };

  // 初期キャンバス幅を1050pxに固定してOSMDを生成
  container.style.width = "1050px";

  const osmd = new opensheetmusicdisplay.OpenSheetMusicDisplay(container, {
    autoResize: false, // 画面サイズによるページ割れ・幅圧縮を防ぐ
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

  // レイアウトと再描画
  function applyLayoutAndRender() {
    if (!osmd.sheet) return;

    const fmtKey = formatSelect.value;
    const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];

    // 1. OSMDが小節幅を計算するための十分なコンテナ幅（px）をセット
    container.style.width = `${formatSpec.canvasWidthPx}px`;

    // 2. 公式オプションメソッド setOptions を使用して用紙フォーマットを更新
    osmd.setOptions({
      pageFormat: formatSpec.osmdOption
    });

    // 3. 1段の小節数 (0 = 自動組版)
    const measures = parseInt(measuresSelect.value, 10);
    osmd.EngravingRules.RenderXMeasuresPerLineAkaSystem = measures;

    // 4. ズーム倍率
    osmd.zoom = parseFloat(scaleSlider.value);

    // 5. 描画
    osmd.render();
  }

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

  // 【OSMD公式仕様準拠】SVGの比率を完全に維持したベクターPDF出力
  async function downloadPdfDirectly() {
    const backends = osmd.drawer && osmd.drawer.Backends;
    if (!backends || backends.length === 0) {
      showStatus("出力対象の楽譜が見つかりません。", true);
      return;
    }

    try {
      btnDownloadPdf.disabled = true;
      showStatus("PDFファイルを生成中...");

      const fmtKey = formatSelect.value;
      const formatSpec = PAPER_FORMATS[fmtKey] || PAPER_FORMATS["A4_P"];
      const orientation = formatSpec.heightMm > formatSpec.widthMm ? "portrait" : "landscape";

      const { jsPDF } = window.jspdf;
      // ポイント単位（pt）でPDFドキュメントを初期化
      const pdf = new jsPDF({
        orientation: orientation,
        unit: "pt",
        format: [
          (formatSpec.widthMm / 25.4) * 72,
          (formatSpec.heightMm / 25.4) * 72
        ],
        compress: true
      });

      const pdfPageWidth = pdf.internal.pageSize.getWidth();
      const pdfPageHeight = pdf.internal.pageSize.getHeight();

      for (let idx = 0; idx < backends.length; idx++) {
        if (idx > 0) {
          pdf.addPage([pdfPageWidth, pdfPageHeight], orientation);
        }
        showStatus(`PDFを生成中... (${idx + 1} / ${backends.length} ページ)`);

        const svgElement = backends[idx].getSvgElement();

        // SVG本来の解像度・アスペクト比を取得
        const vb = svgElement.viewBox && svgElement.viewBox.baseVal;
        const svgW = (vb && vb.width > 0) ? vb.width : (parseFloat(svgElement.getAttribute("width")) || formatSpec.canvasWidthPx);
        const svgH = (vb && vb.height > 0) ? vb.height : (parseFloat(svgElement.getAttribute("height")) || (svgW * 1.414));

        // 用紙横幅いっぱいに収めたときの正確な高さを計算（縦横比率を完全保持）
        const renderedHeight = pdfPageWidth * (svgH / svgW);

        // 高さがページを超える場合は全体を縮小
        let targetW = pdfPageWidth;
        let targetH = renderedHeight;
        if (renderedHeight > pdfPageHeight) {
          const ratio = pdfPageHeight / renderedHeight;
          targetW *= ratio;
          targetH = pdfPageHeight;
        }

        // svg2pdf.js v2 の公式仕様に沿って描画
        await pdf.svg(svgElement, {
          x: 0,
          y: 0,
          width: targetW,
          height: targetH
        });
      }

      pdf.save(`${currentFileName}.pdf`);
      showStatus(`ダウンロード完了: ${currentFileName}.pdf`);

    } catch (err) {
      console.error(err);
      showStatus(`PDF生成エラー: ${err.message}`, true);
    } finally {
      btnDownloadPdf.disabled = false;
    }
  }

  // イベントリスナー
  formatSelect.addEventListener("change", applyLayoutAndRender);
  measuresSelect.addEventListener("change", applyLayoutAndRender);

  scaleSlider.addEventListener("input", (e) => {
    scaleLabel.textContent = `${Math.round(e.target.value * 100)}%`;
  });
  scaleSlider.addEventListener("change", applyLayoutAndRender);

  quantizeSelect.addEventListener("change", () => {
    if (lastLoadedFile && lastLoadedFile.name.match(/\.midi?$/i)) {
      handleFile(lastLoadedFile);
    }
  });

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
