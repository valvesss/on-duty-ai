/* Head-pose radar shared by the dashboard and the setup wizard.
 *   const r = Radar(canvas); r.set(status)   // call with each /status payload; it animates itself
 * x = head yaw (turn), y = head pitch (down is down). Zones are where you work; the red band is where I'd nag. */
function Radar(canvas, opts = {}) {
  const dpr = devicePixelRatio || 1, W = canvas.width = (opts.size || 300) * dpr, H = canvas.height = (opts.size || 300) * dpr;
  canvas.style.width = canvas.style.maxWidth = (opts.size || 300) + 'px'; canvas.style.aspectRatio = '1';
  const g = canvas.getContext('2d'), X = [-50, 50], Y = [-30, 40];
  const px = v => (v - X[0]) / (X[1] - X[0]) * W, py = v => (v - Y[0]) / (Y[1] - Y[0]) * H;
  let st = null, dot = null, trail = [], raf = 0;
  const lerp = (a, b, k) => a + (b - a) * k;

  function frame() {
    if (!canvas.isConnected) return;
    raf = requestAnimationFrame(frame);
    const s = st, pose = s && s.pose, cal = (s && s.calibration) || {}, th = (s && s.cfg) || {};
    const zones = (s && s.cal && s.cal.open && s.cal.zones.length ? s.cal.zones : cal.zone_data) || [], phone = s && s.cal && s.cal.phone;
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#0f172a'; g.beginPath(); g.roundRect(0, 0, W, H, 22 * dpr); g.fill();
    g.save(); g.beginPath(); g.roundRect(0, 0, W, H, 22 * dpr); g.clip();
    g.strokeStyle = '#ffffff14'; g.lineWidth = dpr;
    for (let x = -40; x <= 40; x += 20) { g.beginPath(); g.moveTo(px(x), 0); g.lineTo(px(x), H); g.stroke(); }
    for (let y = -20; y <= 30; y += 10) { g.beginPath(); g.moveTo(0, py(y)); g.lineTo(W, py(y)); g.stroke(); }
    g.strokeStyle = '#ffffff30'; g.beginPath(); g.moveTo(px(0), 0); g.lineTo(px(0), H); g.moveTo(0, py(0)); g.lineTo(W, py(0)); g.stroke();
    // alert area under each zone
    const pd = th.pitch_delta || 12;
    for (const z of zones) {
      const top = py(z.pitch + pd), x0 = px(z.yaw - 25), x1 = px(z.yaw + 25);
      const grd = g.createLinearGradient(0, top, 0, H); grd.addColorStop(0, '#ef444455'); grd.addColorStop(1, '#ef444411');
      g.fillStyle = grd; g.fillRect(x0, top, x1 - x0, H - top);
      g.setLineDash([6 * dpr, 5 * dpr]); g.strokeStyle = '#f87171'; g.lineWidth = 2 * dpr; g.beginPath(); g.moveTo(x0, top); g.lineTo(x1, top); g.stroke(); g.setLineDash([]);
      g.fillStyle = '#22c55e33'; g.strokeStyle = '#22c55e'; g.lineWidth = 2 * dpr; g.beginPath(); g.ellipse(px(z.yaw), py(z.pitch), 38 * dpr, 30 * dpr, 0, 0, 7); g.fill(); g.stroke();
      g.fillStyle = '#bbf7d0'; g.font = `700 ${12 * dpr}px system-ui`; g.textAlign = 'center'; g.fillText(z.name, px(z.yaw), py(z.pitch) - 38 * dpr);
    }
    if (phone) { g.font = `${22 * dpr}px system-ui`; g.textAlign = 'center'; g.fillText('📱', px(phone.yaw), py(phone.pitch) + 8 * dpr); }
    // you
    if (pose) {
      const tx = px(pose.yaw), ty = py(pose.pitch);
      dot = dot ? { x: lerp(dot.x, tx, .28), y: lerp(dot.y, ty, .28) } : { x: tx, y: ty };
      trail.push({ ...dot }); if (trail.length > 28) trail.shift();
      const hot = s.down || s.phone;
      trail.forEach((p, i) => { g.globalAlpha = i / trail.length * .5; g.fillStyle = hot ? '#fca5a5' : '#e2e8f0'; g.beginPath(); g.arc(p.x, p.y, (2 + i / 6) * dpr, 0, 7); g.fill(); });
      g.globalAlpha = 1; g.shadowColor = hot ? '#ef4444' : '#38bdf8'; g.shadowBlur = 18 * dpr;
      g.fillStyle = hot ? '#ef4444' : '#38bdf8'; g.beginPath(); g.arc(dot.x, dot.y, 9 * dpr, 0, 7); g.fill(); g.shadowBlur = 0;
      g.strokeStyle = '#fff'; g.lineWidth = 2.5 * dpr; g.stroke();
    } else { dot = null; trail = []; g.fillStyle = '#94a3b8'; g.font = `700 ${14 * dpr}px system-ui`; g.textAlign = 'center'; g.fillText('…', W / 2, H / 2); }
    g.restore();
    g.fillStyle = '#94a3b8aa'; g.font = `600 ${11 * dpr}px system-ui`; g.textAlign = 'left'; g.fillText('↑', 10 * dpr, 18 * dpr); g.fillText('↓', 10 * dpr, H - 8 * dpr); g.textAlign = 'right'; g.fillText('→', W - 10 * dpr, py(0) - 6 * dpr);
  }
  return { set(s) { st = s; if (!raf) raf = requestAnimationFrame(frame); }, stop() { cancelAnimationFrame(raf); raf = 0; } };
}
