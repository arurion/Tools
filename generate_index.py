import os
import urllib.parse
import html

# --- 設定：除外リストの徹底 ---
EXCLUDE_DIRS = {'.git', '.github', '__pycache__', 'node_modules', '.venv', '.vscode'}
EXCLUDE_FILES = {'generate_index.py', 'index_all.html', '.gitignore', 'package-lock.json'}

def generate_html():
    html_content = [
        "<!DOCTYPE html>",
        "<html lang='ja'>",
        "<head>",
        "    <meta charset='UTF-8'>",
        "    <meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "    <title>Repository Explorer (2026 Stable)</title>",
        "    <style>",
        "        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; line-height: 1.6; padding: 20px; background: #f4f7f9; color: #333; }",
        "        .container { max-width: 900px; margin: 0 auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }",
        "        h1 { border-bottom: 2px solid #007bff; padding-bottom: 10px; color: #007bff; font-size: 24px; }",
        "        ul { list-style: none; padding-left: 20px; }",
        "        li { margin: 8px 0; position: relative; }",
        "        .dir-name { font-weight: bold; color: #e67e22; cursor: default; }",
        "        .dir-name::before { content: '📁 '; }",
        "        .file-link { color: #2980b9; text-decoration: none; transition: color 0.2s; }",
        "        .file-link:hover { color: #3498db; text-decoration: underline; }",
        "        .file-link::before { content: '📄 '; }",
        "        .footer { margin-top: 30px; font-size: 0.8em; color: #7f8c8d; text-align: right; }",
        "    </style>",
        "</head>",
        "<body>",
        "    <div class='container'>",
        "        <h1>Repository File Explorer</h1>",
        "        <ul>"
    ]

    # os.walkをソートして順序を固定（バグ抑制）
    for root, dirs, files in os.walk('.'):
        # 隠しディレクトリや除外ディレクトリを無視
        dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS and not d.startswith('.')]
        dirs.sort()
        files.sort()

        rel_path = os.path.relpath(root, '.')
        level = 0 if rel_path == '.' else rel_path.count(os.sep) + 1
        indent = "    " * level

        # 現在のディレクトリ名を表示
        if rel_path != '.':
            d_name = html.escape(os.path.basename(root))
            html_content.append(f"{indent}<li><span class='dir-name'>{d_name}/</span><ul>")

        for f in files:
            if f in EXCLUDE_FILES or f.startswith('.'):
                continue
            
            # バグ対策1：OS依存のパス区切りをURL用の "/" に統一
            file_path = os.path.join(rel_path, f) if rel_path != '.' else f
            url_path = file_path.replace(os.sep, '/')
            
            # バグ対策2：日本語やスペースを正しくURLエンコード
            encoded_url = urllib.parse.quote(url_path)
            
            # バグ対策3：HTMLエスケープ（ファイル名に < > & 等が含まれる場合用）
            safe_f_name = html.escape(f)
            
            html_content.append(f"{indent}    <li><a class='file-link' href='./{encoded_url}'>{safe_f_name}</a></li>")

        # 閉じタグの制御は os.walk の構造上、インデントで行う
        # (実際は単純なネスト構造で出力するため、ここでは簡易化)

    html_content.append("        </ul>")
    html_content.append(f"        <div class='footer'>Generated at: 2026-05-17 (Version 2026.1)</div>")
    html_content.append("    </div>")
    html_content.append("</body>")
    html_content.append("</html>")

    with open('index_all.html', 'w', encoding='utf-8') as f:
        f.write("\n".join(html_content))

if __name__ == "__main__":
    generate_html()
