/* 色卡生成器 — 纯前端实现（对应原 Python 版 colorcard 的取色与排版逻辑） */
(function () {
  'use strict';

  var DEFAULT_PROMPT = '电影静帧质感，冷青色调分级，低饱和配色，蓝黑色死黑阴影，薄雾中柔和的顶部漫射光，低 Key 布光，浅景深，变形宽银幕气质，哑光表面，细腻胶片颗粒，浅青灰色高光';

  var W = 1600;            // 输出宽度
  var MARGIN = 40;         // W // 40
  var GAP = 32;            // W // 50
  var STRIP_H = 64;        // W // 25
  var SWATCH_GAP = 2;
  var FONT_RATIO = 45;     // W // 45 = 35
  var TEXT_COLOR = '#c8c8c8';
  var LINE_SPACING = 1.5;
  var N_COLORS = 10;
  var MAX_SIDE = 600;      // 取色分析时的最长边
  var MAX_SAMPLES = 40000; // 最多参与聚类的像素数

  var $ = function (id) { return document.getElementById(id); };
  var drop = $('drop'), fileInput = $('fileInput'), fileName = $('fileName'), fileChip = $('fileChip');
  var promptEl = $('prompt'), genBtn = $('gen'), genLabel = $('genLabel'), saveBtn = $('save');
  var statusEl = $('status'), canvas = $('canvas'), empty = $('empty');
  var dimsEl = $('dims'), paletteEl = $('palette');

  var state = { bitmap: null, fileName: '', palette: [], busy: false };
  var measure = document.createElement('canvas').getContext('2d');

  try {
    var saved = localStorage.getItem('cc.prompt');
    promptEl.value = saved === null ? DEFAULT_PROMPT : saved;
  } catch (e) {
    promptEl.value = DEFAULT_PROMPT;
  }

  function setStatus(text, kind) {
    statusEl.textContent = text;
    statusEl.className = 'status' + (kind ? ' ' + kind : '');
  }

  function stemOf(name) {
    var i = name.lastIndexOf('.');
    return i > 0 ? name.slice(0, i) : name;
  }

  /* ---------- 图片载入 ---------- */

  function loadBitmap(file) {
    if (!file) return Promise.reject(new Error('没有选择文件'));
    var isImage = /^image\//.test(file.type || '') || /\.(jpe?g|png|webp)$/i.test(file.name || '');
    if (!isImage) return Promise.reject(new Error('无法读取该文件，请确认它是 JPG、PNG 或 WebP 图片'));

    if (window.createImageBitmap) {
      var p;
      try {
        p = createImageBitmap(file, { imageOrientation: 'from-image' });
      } catch (e) {
        p = createImageBitmap(file);
      }
      return Promise.resolve(p).catch(function () { return loadViaImage(file); });
    }
    return loadViaImage(file);
  }

  function loadViaImage(file) {
    return new Promise(function (resolve, reject) {
      var img = new Image();
      var url = URL.createObjectURL(file);
      img.onload = function () { URL.revokeObjectURL(url); resolve(img); };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error('无法读取该文件，请确认它是 JPG、PNG 或 WebP 图片')); };
      img.src = url;
    });
  }

  function handleFile(file) {
    if (!file) return;
    state.bitmap = null;
    canvas.classList.remove('show');
    empty.style.display = '';
    state.palette = [];
    renderPalette([]);
    saveBtn.disabled = true;
    dimsEl.textContent = '1600 × —';
    setStatus('正在读取图片…');

    loadBitmap(file).then(function (bmp) {
      state.bitmap = bmp;
      state.fileName = file.name || 'image';
      fileName.textContent = state.fileName;
      fileChip.classList.add('show');
      drop.classList.add('loaded');
      setStatus('已载入 ' + state.fileName + '，点击「生成色卡」开始取色', 'ok');
    }).catch(function (err) {
      setStatus(err.message || '图片载入失败', 'err');
    });
  }

  /* ---------- 取色（median-cut，等价于 PIL MEDIANCUT 的思路） ---------- */

  function analyze(bitmap) {
    var w = bitmap.width || bitmap.naturalWidth;
    var h = bitmap.height || bitmap.naturalHeight;
    var scale = Math.min(1, MAX_SIDE / Math.max(w, h));
    var aw = Math.max(1, Math.round(w * scale));
    var ah = Math.max(1, Math.round(h * scale));

    var c = document.createElement('canvas');
    c.width = aw; c.height = ah;
    var ctx = c.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(bitmap, 0, 0, aw, ah);
    var data = ctx.getImageData(0, 0, aw, ah).data;

    var packed = [];
    for (var i = 0, n = data.length; i < n; i += 4) {
      var a = data[i + 3];
      if (a === 0) continue;
      var r = Math.round(data[i] * a / 255);
      var g = Math.round(data[i + 1] * a / 255);
      var b = Math.round(data[i + 2] * a / 255);
      packed.push((r << 16) | (g << 8) | b);
    }
    var total = packed.length;
    if (!total) throw new Error('图片没有可分析的内容');

    if (total > MAX_SAMPLES) {
      var stride = total / MAX_SAMPLES;
      var sampled = new Array(MAX_SAMPLES);
      for (var j = 0; j < MAX_SAMPLES; j++) sampled[j] = packed[Math.floor(j * stride)];
      packed = sampled;
      total = MAX_SAMPLES;
    }

    var hist = new Map();
    for (var k = 0; k < packed.length; k++) {
      var key = packed[k];
      hist.set(key, (hist.get(key) || 0) + 1);
    }
    var colors = [];
    hist.forEach(function (count, key) {
      colors.push({
        r: (key >> 16) & 255,
        g: (key >> 8) & 255,
        b: key & 255,
        c: count
      });
    });
    return { colors: colors, total: total };
  }

  function makeBox(colors) {
    var minR = 255, maxR = 0, minG = 255, maxG = 0, minB = 255, maxB = 0, count = 0;
    for (var i = 0; i < colors.length; i++) {
      var c = colors[i];
      if (c.r < minR) minR = c.r; if (c.r > maxR) maxR = c.r;
      if (c.g < minG) minG = c.g; if (c.g > maxG) maxG = c.g;
      if (c.b < minB) minB = c.b; if (c.b > maxB) maxB = c.b;
      count += c.c;
    }
    return {
      colors: colors, count: count,
      minR: minR, maxR: maxR, minG: minG, maxG: maxG, minB: minB, maxB: maxB,
      range: Math.max(maxR - minR, maxG - minG, maxB - minB)
    };
  }

  function splitBox(box) {
    var cr = box.maxR - box.minR, cg = box.maxG - box.minG, cb = box.maxB - box.minB;
    var ch = (cr >= cg && cr >= cb) ? 'r' : (cg >= cb ? 'g' : 'b');
    var sorted = box.colors.slice().sort(function (a, b) { return a[ch] - b[ch]; });
    var half = box.count / 2, acc = 0, idx = 0;
    for (var i = 0; i < sorted.length - 1; i++) {
      acc += sorted[i].c;
      if (acc >= half) { idx = i + 1; break; }
      idx = i + 2;
    }
    if (idx < 1) idx = 1;
    if (idx >= sorted.length) idx = sorted.length - 1;
    if (sorted.length < 2) return null;
    return [makeBox(sorted.slice(0, idx)), makeBox(sorted.slice(idx))];
  }

  function medianCut(colors, n) {
    var boxes = [makeBox(colors)];
    var guard = 0;
    while (boxes.length < n && guard++ < 200) {
      var pick = -1, best = -1;
      for (var i = 0; i < boxes.length; i++) {
        if (boxes[i].colors.length < 2 || boxes[i].range === 0) continue;
        var score = boxes[i].range * Math.sqrt(boxes[i].count);
        if (score > best) { best = score; pick = i; }
      }
      if (pick < 0) break;
      var parts = splitBox(boxes[pick]);
      if (!parts) { boxes[pick].range = 0; continue; }
      boxes.splice(pick, 1, parts[0], parts[1]);
    }
    var out = boxes.map(function (b) {
      var sr = 0, sg = 0, sb = 0, c = 0;
      for (var i = 0; i < b.colors.length; i++) {
        var x = b.colors[i];
        sr += x.r * x.c; sg += x.g * x.c; sb += x.b * x.c; c += x.c;
      }
      return {
        rgb: c ? [Math.round(sr / c), Math.round(sg / c), Math.round(sb / c)] : [0, 0, 0],
        count: b.count
      };
    });
    out.sort(function (a, b) { return b.count - a.count; });
    return out;
  }

  function extractPalette(analysis) {
    var result = medianCut(analysis.colors, N_COLORS);
    var total = analysis.total || 1;
    var palette = result.map(function (x) {
      return { rgb: x.rgb, ratio: x.count / total };
    });
    while (palette.length < N_COLORS) palette.push({ rgb: [0, 0, 0], ratio: 0 });
    return palette.slice(0, N_COLORS);
  }

  /* ---------- 排版渲染 ---------- */

  function fontCss(size) {
    return size + 'px "Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Microsoft YaHei",sans-serif';
  }

  function wrapText(text, font, maxWidth) {
    measure.font = font;
    var lines = [];
    var paras = String(text).split(/\r\n|\r|\n/);
    for (var p = 0; p < paras.length; p++) {
      var cur = '';
      for (var ch of paras[p]) {
        if (measure.measureText(cur + ch).width > maxWidth) {
          lines.push(cur);
          cur = ch;
        } else {
          cur += ch;
        }
      }
      lines.push(cur);
    }
    return lines.filter(function (line) { return line.length > 0; });
  }

  function renderCard(bitmap, palette, promptText) {
    var imgW = W - MARGIN * 2;
    var bw = bitmap.width || bitmap.naturalWidth;
    var bh = bitmap.height || bitmap.naturalHeight;
    var imgH = Math.max(1, Math.floor(bh * imgW / bw));
    var stripBottom = MARGIN + imgH + GAP + STRIP_H;

    var fontSize = Math.floor(W / FONT_RATIO);
    var font = fontCss(fontSize);
    var lines = [];
    var lineH = 0;
    if (promptText.trim()) {
      lines = wrapText(promptText.trim(), font, imgW);
      lineH = Math.trunc(fontSize * LINE_SPACING);
    }

    var cardH = lines.length
      ? stripBottom + GAP + lineH * lines.length + GAP
      : stripBottom + GAP;

    canvas.width = W;
    canvas.height = cardH;
    var ctx = canvas.getContext('2d');
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, W, cardH);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(bitmap, MARGIN, MARGIN, imgW, imgH);

    var stripTop = MARGIN + imgH + GAP;
    var swatchW = Math.floor((imgW - (N_COLORS - 1) * SWATCH_GAP) / N_COLORS);
    for (var i = 0; i < N_COLORS; i++) {
      var rgb = (i < palette.length && palette[i].rgb) ? palette[i].rgb : [0, 0, 0];
      var left = MARGIN + i * (swatchW + SWATCH_GAP);
      var right = i < N_COLORS - 1 ? left + swatchW : MARGIN + imgW;
      ctx.fillStyle = 'rgb(' + rgb[0] + ',' + rgb[1] + ',' + rgb[2] + ')';
      ctx.fillRect(left, stripTop, right - left, STRIP_H);
    }

    if (lines.length) {
      ctx.font = font;
      ctx.fillStyle = TEXT_COLOR;
      ctx.textBaseline = 'top';
      for (var j = 0; j < lines.length; j++) {
        ctx.fillText(lines[j], MARGIN, stripBottom + GAP + j * lineH);
      }
    }
    return { width: W, height: cardH, lines: lines.length };
  }

  /* ---------- 界面 ---------- */

  function hex(rgb) {
    var s = '#';
    for (var i = 0; i < 3; i++) {
      var v = rgb[i].toString(16).toUpperCase();
      s += v.length < 2 ? '0' + v : v;
    }
    return s;
  }

  function renderPalette(palette) {
    paletteEl.innerHTML = '';
    for (var i = 0; i < N_COLORS; i++) {
      var item = palette[i];
      var chip = document.createElement('div');
      chip.className = 'chip' + (item ? '' : ' empty');
      if (item) {
        chip.style.background = 'rgb(' + item.rgb.join(',') + ')';
        var h = document.createElement('div'); h.className = 'hex'; h.textContent = hex(item.rgb);
        var p = document.createElement('div'); p.className = 'pct'; p.textContent = (item.ratio * 100).toFixed(1) + '%';
        chip.appendChild(h); chip.appendChild(p);
      }
      paletteEl.appendChild(chip);
    }
  }

  function fitPreview() {
    if (!canvas.classList.contains('show')) return;
    var box = $('preview');
    var pad = 36;
    var availW = Math.max(120, box.clientWidth - pad);
    var availH = Math.max(120, box.clientHeight - pad);
    var scale = Math.min(availW / canvas.width, availH / canvas.height, 1);
    canvas.style.width = Math.round(canvas.width * scale) + 'px';
    canvas.style.height = Math.round(canvas.height * scale) + 'px';
  }

  window.addEventListener('resize', fitPreview);

  function generate() {
    if (state.busy) return;
    if (!state.bitmap) {
      setStatus('请先拖入或选择一张图片', 'err');
      drop.classList.remove('drag'); drop.classList.add('drag');
      setTimeout(function () { drop.classList.remove('drag'); }, 220);
      fileInput.click();
      return;
    }
    state.busy = true;
    genBtn.disabled = true;
    saveBtn.disabled = true;
    genLabel.textContent = '分析中…';
    setStatus('正在分析图片主色…');

    setTimeout(function () {
      try {
        var analysis = analyze(state.bitmap);
        var palette = extractPalette(analysis);
        state.palette = palette;
        setStatus('正在排布色卡…');
        genLabel.textContent = '生成中…';

        setTimeout(function () {
          try {
            var info = renderCard(state.bitmap, palette, promptEl.value || '');
            empty.style.display = 'none';
            canvas.classList.add('show');
            fitPreview();
            $('preview').scrollTop = 0;
            saveBtn.disabled = false;
            dimsEl.textContent = info.width + ' × ' + info.height + ' px';
            renderPalette(palette);
            setStatus('色卡已生成，可以保存 PNG', 'ok');
            try { localStorage.setItem('cc.prompt', promptEl.value); } catch (e) {}
          } catch (e2) {
            setStatus(e2.message || '色卡生成失败', 'err');
          } finally {
            state.busy = false;
            genBtn.disabled = false;
            genLabel.textContent = '生成色卡';
          }
        }, 20);
      } catch (err) {
        state.busy = false;
        genBtn.disabled = false;
        genLabel.textContent = '生成色卡';
        setStatus(err.message || '图片没有可分析的内容', 'err');
      }
    }, 20);
  }

  function save() {
    if (!canvas.classList.contains('show')) {
      setStatus('请先生成色卡', 'err');
      return;
    }
    var name = stemOf(state.fileName || '色卡') + '_色卡.png';

    if (window.chrome && window.chrome.webview) {
      setStatus('请在保存对话框中选择位置…');
      window.chrome.webview.postMessage(JSON.stringify({
        cmd: 'saveImage',
        dataUrl: canvas.toDataURL('image/png'),
        name: name
      }));
      return;
    }

    canvas.toBlob(function (blob) {
      if (!blob) { setStatus('导出失败，请重试', 'err'); return; }
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url; a.download = name;
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      setTimeout(function () { URL.revokeObjectURL(url); }, 2000);
      setStatus('已导出：' + name, 'ok');
    }, 'image/png');
  }

  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.addEventListener('message', function (e) {
      var d = e.data;
      if (!d || d.type !== 'save-result') return;
      if (d.ok && d.path) {
        setStatus('已保存：' + d.path, 'ok');
      } else if (!d.ok) {
        if (d.error) setStatus('保存失败：' + d.error, 'err');
        else setStatus('已取消保存', '');
      }
    });
  }

  /* ---------- 事件 ---------- */

  drop.addEventListener('click', function () { fileInput.click(); });
  fileInput.addEventListener('change', function () {
    handleFile(this.files && this.files[0]);
    this.value = '';
  });

  ['dragenter', 'dragover'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      drop.classList.add('drag');
    });
  });
  ['dragleave', 'dragend'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) {
      e.preventDefault(); e.stopPropagation();
      if (!drop.contains(e.relatedTarget)) drop.classList.remove('drag');
    });
  });
  drop.addEventListener('drop', function (e) {
    e.preventDefault(); e.stopPropagation();
    drop.classList.remove('drag');
    var file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
    handleFile(file);
  });

  // 防止把图片拖到页面空白处时浏览器直接打开图片
  window.addEventListener('dragover', function (e) { e.preventDefault(); });
  window.addEventListener('drop', function (e) { e.preventDefault(); });

  genBtn.addEventListener('click', generate);
  saveBtn.addEventListener('click', save);

  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); generate(); }
  });

  renderPalette([]);
})();
