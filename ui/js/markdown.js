const Markdown = {
  render(md) {
    if (!md) return '';
    let escaped = md
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    escaped = escaped.replace(/```(\w*)\n?([\s\S]*?)```/g, '<pre><code class="lang-$1">$2</code></pre>');
    escaped = escaped.replace(/`([^`]+)`/g, '<code>$1</code>');

    escaped = escaped.replace(/##### (.+)/g, '<h5>$1</h5>');
    escaped = escaped.replace(/#### (.+)/g, '<h4>$1</h4>');
    escaped = escaped.replace(/### (.+)/g, '<h3>$1</h3>');
    escaped = escaped.replace(/## (.+)/g, '<h2>$1</h2>');
    escaped = escaped.replace(/# (.+)/g, '<h1>$1</h1>');

    escaped = escaped.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    escaped = escaped.replace(/\*(.+?)\*/g, '<em>$1</em>');
    escaped = escaped.replace(/~~(.+?)~~/g, '<del>$1</del>');
    escaped = escaped.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

    const lines = escaped.split('\n');
    const result = [];
    let inList = false;
    let listType = null;
    let inParagraph = false;
    let inTable = 0; // 0=not in table, 1=in thead, 2=in tbody

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      if (/^<h[1-5]>/.test(line) || /^<pre>/.test(line)) {
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }
        if (inTable) { result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>'); inTable = 0; }
        result.push(line);
        continue;
      }

      if (/^<\/?pre>/.test(line) || /^<\/?code>/.test(line)) {
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }
        if (inTable) { result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>'); inTable = 0; }
        result.push(line);
        continue;
      }

      const tableMatch = line.match(/^\|(.+)\|$/);
      if (tableMatch) {
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }
        const cells = tableMatch[1].split('|').map(c => c.trim());
        const isSep = cells.every(c => /^-{3,}$/.test(c));
        if (isSep) {
          if (inTable === 1) {
            result.push('</thead><tbody>');
            inTable = 2;
          } else if (inTable === 0) {
            result.push('<table><thead></thead><tbody>');
            inTable = 2;
          }
          continue;
        }
        if (inTable === 0) {
          result.push('<table><thead><tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr>');
          inTable = 1;
        } else if (inTable === 1) {
          result.push('<tr>' + cells.map(c => `<th>${c}</th>`).join('') + '</tr>');
        } else {
          result.push('<tr>' + cells.map(c => `<td>${c}</td>`).join('') + '</tr>');
        }
        continue;
      }

      if (inTable) {
        result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>');
        inTable = 0;
      }

      if (/^-{3,}$/.test(line.trim())) {
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }
        if (inTable) { result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>'); inTable = 0; }
        result.push('<hr>');
        continue;
      }

      const ulMatch = line.match(/^[-*] (.+)/);
      const olMatch = line.match(/^\d+[.)] (.+)/);

      if (ulMatch || olMatch) {
        const content = ulMatch ? ulMatch[1] : olMatch[1];
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        result.push('<li>' + content + '</li>');
        continue;
      }

      if (line.trim() === '') {
        if (inParagraph) { result.push('</p>'); inParagraph = false; }
        if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }
        if (inTable) { result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>'); inTable = 0; }
        continue;
      }

      if (inList) { result.push('</' + listType + '>'); inList = false; listType = null; }

      if (!inParagraph) {
        result.push('<p>');
        inParagraph = true;
      } else {
        result.push('<br>');
      }
      result.push(line);
    }

    if (inParagraph) result.push('</p>');
    if (inList) result.push('</' + listType + '>');
    if (inTable) {
      result.push(inTable === 1 ? '</thead></table>' : '</tbody></table>');
    }

    return result.join('\n');
  }
};
