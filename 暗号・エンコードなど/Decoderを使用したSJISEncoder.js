/**
 * Shift_JIS Encoder for Embedded JavaScript
 * 
 * 仕組み:
 * TextDecoder('shift-jis') を使用してバイト列から文字への逆引きを行い、
 * メモリ上に Unicode -> SJIS の変換テーブル(Uint16Array)を作成します。
 */

// 変換テーブル (BMP領域 0x0000 - 0xFFFF をカバー)
// メモリ消費量: 約128KB
let unicodeToSjisTable = null;

/**
 * SJISテーブルを初期化します。
 * アプリケーションの起動時に一度だけ実行してください。
 */
function initializeSjisTable() {
    if (unicodeToSjisTable) return; // 作成済みなら何もしない

    // 0xFFFF で初期化（0x00は有効なSJISコード(NULL)なので、未使用値として0xFFFFを使う）
    unicodeToSjisTable = new Uint16Array(65536).fill(0xFFFF);

    const decoder = new TextDecoder('shift-jis');

    // 1. 1バイト文字 (ASCII + 半角カナ) の総当たり
    // 範囲: 0x00-0xFF
    // ※ 実際には 0x81-0x9F, 0xE0-0xFC は2バイト文字の1バイト目のため、
    //    単独でデコードすると文字化けや無視が起きますが、有効な範囲だけ採用します。
    const buffer1 = new Uint8Array(1);
    for (let b = 0; b <= 0xFF; b++) {
        buffer1[0] = b;
        const char = decoder.decode(buffer1);
        if (char.length === 1) {
            const codePoint = char.charCodeAt(0);
            // まだ登録されていない、かつ置換文字(U+FFFD)でない場合のみ登録
            if (unicodeToSjisTable[codePoint] === 0xFFFF && codePoint !== 0xFFFD) {
                unicodeToSjisTable[codePoint] = b;
            }
        }
    }

    // 2. 2バイト文字 (漢字など) の総当たり
    // SJISの有効範囲:
    // 第1バイト: 0x81-0x9F, 0xE0-0xFC
    // 第2バイト: 0x40-0x7E, 0x80-0xFC
    const leads = [];
    for (let i = 0x81; i <= 0x9F; i++) leads.push(i);
    for (let i = 0xE0; i <= 0xFC; i++) leads.push(i);

    const trails = [];
    for (let i = 0x40; i <= 0x7E; i++) trails.push(i);
    for (let i = 0x80; i <= 0xFC; i++) trails.push(i);

    const buffer2 = new Uint8Array(2);
    
    for (const lead of leads) {
        buffer2[0] = lead;
        for (const trail of trails) {
            buffer2[1] = trail;
            const char = decoder.decode(buffer2);
            if (char.length === 1) {
                const codePoint = char.charCodeAt(0);
                // 上書きしない (Shift_JISは重複マッピングがあるが、標準的なものを優先するため先勝ち、または後勝ち)
                // Windows-31J準拠の場合、重複はNEC選定IBM拡張などが絡むが、
                // TextDecoderの挙動に従い、まだ未登録の領域を埋める方針とする。
                if (unicodeToSjisTable[codePoint] === 0xFFFF && codePoint !== 0xFFFD) {
                    // 上位バイトを左に8ビットシフトして結合して格納 (例: 0x8140)
                    unicodeToSjisTable[codePoint] = (lead << 8) | trail;
                }
            }
        }
    }
}

/**
 * 文字列をShift_JISのUint8Arrayにエンコードします。
 * 対応していない文字は '?' (0x3F) に変換されます。
 * 
 * @param {string} str - 入力文字列
 * @returns {Uint8Array} - SJISバイト列
 */
function encodeSjis(str) {
    if (!unicodeToSjisTable) {
        throw new Error("SjisTable is not initialized. Call initializeSjisTable() first.");
    }

    // 結果格納用の動的配列（または最大サイズを見積もって確保）
    // 文字列長の2倍あればSJISとしては十分（全て全角の場合）
    const output = new Uint8Array(str.length * 2);
    let cursor = 0;

    for (let i = 0; i < str.length; i++) {
        const code = str.charCodeAt(i);
        
        // サロゲートペア対応が必要な場合（絵文字など）
        // SJISには基本的にマッピングできないため、'?'にするか無視する実装が多い。
        // ここではBMP外(0x10000以上)は未対応として '?' にする単純実装。
        
        let sjisCode = 0xFFFF;
        if (code < 65536) {
            sjisCode = unicodeToSjisTable[code];
        }

        if (sjisCode === 0xFFFF) {
            // マッピングなし -> '?' (0x3F)
            output[cursor++] = 0x3F;
        } else if (sjisCode <= 0xFF) {
            // 1バイト文字
            output[cursor++] = sjisCode;
        } else {
            // 2バイト文字 (上位バイト、下位バイトの順に書き込み)
            output[cursor++] = (sjisCode >> 8) & 0xFF;
            output[cursor++] = sjisCode & 0xFF;
        }
    }

    // 実際に使用した長さで切り出す
    return output.slice(0, cursor);
}

// ==========================================
// 使用例
// ==========================================

// 1. 初期化 (アプリ起動時に1回)
initializeSjisTable();

// 2. エンコードテスト
const text = "Hello, 世界！Shift_JISテスト。";
const sjisBytes = encodeSjis(text);

// 結果確認 (Hex表示)
console.log("Input:", text);
console.log("Hex:", Array.from(sjisBytes).map(b => b.toString(16).toUpperCase().padStart(2, '0')).join(' '));

// 念のため TextDecoder で戻して検証
const decoder = new TextDecoder('shift-jis');
console.log("Decoded back:", decoder.decode(sjisBytes));
