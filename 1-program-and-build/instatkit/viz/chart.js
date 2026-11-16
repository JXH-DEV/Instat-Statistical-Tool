/* Hover for the charts: one tooltip for every chart on the page, a crosshair on line charts.
   Reads data-tips (line charts: {h: heading, r: [[colour class, name, value], ...]}) and data-t ("name\nvalue") from the
   SVG written by instatkit.viz.charts. All text goes in through textContent. */
(function () {
  'use strict';
  var tip = document.createElement('div');
  tip.className = 'ctip';
  tip.style.display = 'none';
  document.body.appendChild(tip);
  var guide = null, cache = new WeakMap();

  function el(tag, cls, txt) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (txt !== undefined) e.textContent = txt;
    return e;
  }
  function fill(hit) {
    var svg = hit.ownerSVGElement, tt = hit.getAttribute('data-t');
    tip.replaceChildren();
    if (tt !== null) {
      var parts = tt.split('\n'), v = el('div');
      v.append(el('b', '', parts[1] || ''));
      tip.append(el('div', 'sub', parts[0]), v);
      return true;
    }
    var all = cache.get(svg);
    if (!all) { all = JSON.parse(svg.getAttribute('data-tips') || '[]'); cache.set(svg, all); }
    var d = (all[+hit.getAttribute('data-p') || 0] || [])[+hit.getAttribute('data-i')];
    if (!d) return false;
    tip.append(el('div', 'sub', d.h));
    d.r.forEach(function (r) {
      var row = el('div', 'row ' + r[0]);
      row.append(el('span', 'k'), el('b', '', r[2]), el('span', 'sub', r[1]));
      tip.append(row);
    });
    return true;
  }
  function hide() {
    tip.style.display = 'none';
    if (guide) { guide.setAttribute('visibility', 'hidden'); guide = null; }
  }
  document.addEventListener('pointermove', function (e) {
    var hit = e.target instanceof Element ? e.target.closest('[data-i],[data-t]') : null;
    if (!hit || !hit.ownerSVGElement || !fill(hit)) return hide();
    var x = hit.getAttribute('data-x'), g = hit.ownerSVGElement.querySelector('.guide');
    if (guide && guide !== g) guide.setAttribute('visibility', 'hidden');
    if (g && x !== null) { g.setAttribute('x1', x); g.setAttribute('x2', x); g.setAttribute('visibility', 'visible'); guide = g; }
    tip.style.display = 'block';
    var w = tip.offsetWidth, h = tip.offsetHeight, px = e.clientX + 14, py = e.clientY + 14;
    if (px + w > innerWidth - 4) px = e.clientX - w - 14;
    if (py + h > innerHeight - 4) py = e.clientY - h - 14;
    tip.style.left = Math.max(4, px) + 'px';
    tip.style.top = Math.max(4, py) + 'px';
  });
  document.addEventListener('pointerleave', hide);
  window.addEventListener('scroll', hide, true);
})();
