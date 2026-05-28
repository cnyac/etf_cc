// DotField — 从 react-bits (David Haz, MIT) 移植成原生 JS
// 原版: https://github.com/DavidHDev/react-bits  src/content/Backgrounds/DotField/DotField.jsx
// 用法: new DotField(containerEl, { dotRadius: 1.5, gradientFrom: '#EF4444', ... })
(function (global) {
  const TWO_PI = Math.PI * 2;

  class DotField {
    constructor(container, opts = {}) {
      this.container = container;
      this.opts = Object.assign({
        dotRadius: 1.5,
        dotSpacing: 14,
        cursorRadius: 500,
        cursorForce: 0.1,
        bulgeOnly: true,
        bulgeStrength: 67,
        glowRadius: 160,
        sparkle: false,
        waveAmplitude: 0,
        gradientFrom: 'rgba(168, 85, 247, 0.35)',
        gradientTo: 'rgba(180, 151, 207, 0.25)',
        glowColor: '#120F17',
      }, opts);

      this.dots = [];
      this.mouse = { x: -9999, y: -9999, prevX: -9999, prevY: -9999, speed: 0 };
      this.size = { w: 0, h: 0, offsetX: 0, offsetY: 0 };
      this.glowOpacity = 0;
      this.engagement = 0;
      this.frameCount = 0;
      this.rafId = null;
      this.resizeTimer = null;
      this.glowId = 'dot-field-glow-' + Math.random().toString(36).slice(2, 9);

      this._mount();
      this._bind();
      this._resize();
      this.rafId = requestAnimationFrame(this._tick.bind(this));
      this.speedInterval = setInterval(this._updateMouseSpeed.bind(this), 20);
    }

    _mount() {
      const c = this.container;
      const cs = getComputedStyle(c);
      if (cs.position === 'static') c.style.position = 'relative';
      if (cs.overflow === 'visible') c.style.overflow = 'hidden';

      this.canvas = document.createElement('canvas');
      Object.assign(this.canvas.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%',
      });
      c.appendChild(this.canvas);

      const svgNS = 'http://www.w3.org/2000/svg';
      const svg = document.createElementNS(svgNS, 'svg');
      Object.assign(svg.style, {
        position: 'absolute', inset: '0', width: '100%', height: '100%',
        pointerEvents: 'none',
      });
      const defs = document.createElementNS(svgNS, 'defs');
      const grad = document.createElementNS(svgNS, 'radialGradient');
      grad.setAttribute('id', this.glowId);
      const stop1 = document.createElementNS(svgNS, 'stop');
      stop1.setAttribute('offset', '0%');
      stop1.setAttribute('stop-color', this.opts.glowColor);
      const stop2 = document.createElementNS(svgNS, 'stop');
      stop2.setAttribute('offset', '100%');
      stop2.setAttribute('stop-color', 'transparent');
      grad.appendChild(stop1); grad.appendChild(stop2);
      defs.appendChild(grad);
      svg.appendChild(defs);
      const circle = document.createElementNS(svgNS, 'circle');
      circle.setAttribute('cx', '-9999');
      circle.setAttribute('cy', '-9999');
      circle.setAttribute('r', String(this.opts.glowRadius));
      circle.setAttribute('fill', `url(#${this.glowId})`);
      circle.style.opacity = '0';
      circle.style.willChange = 'opacity';
      svg.appendChild(circle);
      c.appendChild(svg);

      this.svg = svg;
      this.glowEl = circle;
      this.ctx = this.canvas.getContext('2d', { alpha: true });
      this.dpr = Math.min(window.devicePixelRatio || 1, 2);
    }

    _bind() {
      this._onResize = () => {
        clearTimeout(this.resizeTimer);
        this.resizeTimer = setTimeout(this._resize.bind(this), 100);
      };
      this._onMouseMove = (e) => {
        // 用 clientX/Y + 现场 GBCR：兼容 fixed/relative 容器，免疫滚动
        const r = this.container.getBoundingClientRect();
        this.mouse.x = e.clientX - r.left;
        this.mouse.y = e.clientY - r.top;
      };
      window.addEventListener('resize', this._onResize);
      window.addEventListener('mousemove', this._onMouseMove, { passive: true });
    }

    _resize() {
      const rect = this.container.getBoundingClientRect();
      const w = rect.width, h = rect.height;
      this.canvas.width = w * this.dpr;
      this.canvas.height = h * this.dpr;
      this.canvas.style.width = w + 'px';
      this.canvas.style.height = h + 'px';
      this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
      this.size = {
        w, h,
        offsetX: rect.left + window.scrollX,
        offsetY: rect.top + window.scrollY,
      };
      this._buildDots(w, h);
    }

    _buildDots(w, h) {
      const p = this.opts;
      const step = p.dotRadius + p.dotSpacing;
      const cols = Math.floor(w / step);
      const rows = Math.floor(h / step);
      const padX = (w % step) / 2;
      const padY = (h % step) / 2;
      const dots = new Array(rows * cols);
      let idx = 0;
      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const ax = padX + col * step + step / 2;
          const ay = padY + row * step + step / 2;
          dots[idx++] = { ax, ay, sx: ax, sy: ay, vx: 0, vy: 0, x: ax, y: ay };
        }
      }
      this.dots = dots;
    }

    _updateMouseSpeed() {
      const m = this.mouse;
      const dx = m.prevX - m.x, dy = m.prevY - m.y;
      const dist = Math.sqrt(dx * dx + dy * dy);
      m.speed += (dist - m.speed) * 0.5;
      if (m.speed < 0.001) m.speed = 0;
      m.prevX = m.x; m.prevY = m.y;
    }

    _tick() {
      this.frameCount++;
      const dots = this.dots, m = this.mouse, p = this.opts;
      const { w, h } = this.size;
      const len = dots.length;
      const t = this.frameCount * 0.02;

      const targetEng = Math.min(m.speed / 5, 1);
      this.engagement += (targetEng - this.engagement) * 0.06;
      if (this.engagement < 0.001) this.engagement = 0;
      const eng = this.engagement;

      this.glowOpacity += (eng - this.glowOpacity) * 0.08;
      this.glowEl.setAttribute('cx', m.x);
      this.glowEl.setAttribute('cy', m.y);
      this.glowEl.style.opacity = this.glowOpacity;

      const ctx = this.ctx;
      ctx.clearRect(0, 0, w, h);
      const grad = ctx.createLinearGradient(0, 0, w, h);
      grad.addColorStop(0, p.gradientFrom);
      grad.addColorStop(1, p.gradientTo);
      ctx.fillStyle = grad;

      const cr = p.cursorRadius, crSq = cr * cr;
      const rad = p.dotRadius / 2;
      const isBulge = p.bulgeOnly;

      ctx.beginPath();
      for (let i = 0; i < len; i++) {
        const d = dots[i];
        const dx = m.x - d.ax, dy = m.y - d.ay;
        const distSq = dx * dx + dy * dy;

        if (distSq < crSq && eng > 0.01) {
          const dist = Math.sqrt(distSq);
          if (isBulge) {
            const tt = 1 - dist / cr;
            const push = tt * tt * p.bulgeStrength * eng;
            const angle = Math.atan2(dy, dx);
            d.sx += (d.ax - Math.cos(angle) * push - d.sx) * 0.15;
            d.sy += (d.ay - Math.sin(angle) * push - d.sy) * 0.15;
          } else {
            const angle = Math.atan2(dy, dx);
            const move = (500 / dist) * (m.speed * p.cursorForce);
            d.vx += Math.cos(angle) * -move;
            d.vy += Math.sin(angle) * -move;
          }
        } else if (isBulge) {
          d.sx += (d.ax - d.sx) * 0.1;
          d.sy += (d.ay - d.sy) * 0.1;
        }

        if (!isBulge) {
          d.vx *= 0.9; d.vy *= 0.9;
          d.x = d.ax + d.vx; d.y = d.ay + d.vy;
          d.sx += (d.x - d.sx) * 0.1;
          d.sy += (d.y - d.sy) * 0.1;
        }

        let drawX = d.sx, drawY = d.sy;
        if (p.waveAmplitude > 0) {
          drawY += Math.sin(d.ax * 0.03 + t) * p.waveAmplitude;
          drawX += Math.cos(d.ay * 0.03 + t * 0.7) * p.waveAmplitude * 0.5;
        }

        if (p.sparkle) {
          const hash = ((i * 2654435761) ^ (this.frameCount >> 3)) >>> 0;
          if ((hash % 100) < 3) {
            ctx.moveTo(drawX + rad * 1.8, drawY);
            ctx.arc(drawX, drawY, rad * 1.8, 0, TWO_PI);
          } else {
            ctx.moveTo(drawX + rad, drawY);
            ctx.arc(drawX, drawY, rad, 0, TWO_PI);
          }
        } else {
          ctx.moveTo(drawX + rad, drawY);
          ctx.arc(drawX, drawY, rad, 0, TWO_PI);
        }
      }
      ctx.fill();
      this.rafId = requestAnimationFrame(this._tick.bind(this));
    }

    destroy() {
      cancelAnimationFrame(this.rafId);
      clearInterval(this.speedInterval);
      window.removeEventListener('resize', this._onResize);
      window.removeEventListener('mousemove', this._onMouseMove);
      this.canvas.remove();
      this.svg.remove();
    }
  }

  global.DotField = DotField;
})(window);
