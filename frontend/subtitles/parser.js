(function bootstrapSubtitleParser(globalScope) {
  function parseSubtitles(text, filename) {
    if ((filename || '').toLowerCase().endsWith('.vtt')) return parseVtt(text);
    return parseSrt(text);
  }

  function parseSrt(text) {
    const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').trim();
    const blocks = normalized.split(/\n\n+/);
    const cues = [];

    for (const block of blocks) {
      const lines = block.split('\n').filter(Boolean);
      if (lines.length < 2) continue;

      let timeLineIdx = 0;
      if (/^\d+$/.test(lines[0].trim())) timeLineIdx = 1;
      const timeMatch = lines[timeLineIdx]?.match(
        /(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})/
      );
      if (!timeMatch) continue;

      const rawText = lines.slice(timeLineIdx + 1).join(' ').replace(/<[^>]+>/g, '').trim();
      if (!rawText) continue;

      cues.push({ start: parseTime(timeMatch[1]), end: parseTime(timeMatch[2]), text: rawText });
    }

    return cues.sort((a, b) => a.start - b.start);
  }

  function parseVtt(text) {
    const normalized = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
    const blocks = normalized.split(/\n\n+/);
    const cues = [];

    for (const block of blocks) {
      if (block.startsWith('WEBVTT')) continue;
      const lines = block.split('\n').filter(Boolean);
      if (!lines.length) continue;

      let timeLineIdx = 0;
      if (!lines[0].includes('-->')) timeLineIdx = 1;
      const timeMatch = lines[timeLineIdx]?.match(
        /((?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})\s*-->\s*((?:\d{1,2}:)?\d{2}:\d{2}[,.]\d{3})/
      );
      if (!timeMatch) continue;

      const rawText = lines.slice(timeLineIdx + 1).join(' ').replace(/<[^>]+>/g, '').trim();
      if (!rawText) continue;

      cues.push({ start: parseTime(timeMatch[1]), end: parseTime(timeMatch[2]), text: rawText });
    }

    return cues.sort((a, b) => a.start - b.start);
  }

  function parseTime(str) {
    const clean = str.replace(',', '.');
    const parts = clean.split(':').map(Number);
    if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
    return parts[0] * 60 + parts[1];
  }

  globalScope.SubLearnSubtitleParser = {
    parseSubtitles,
    parseSrt,
    parseVtt,
    parseTime,
  };
}(window));
