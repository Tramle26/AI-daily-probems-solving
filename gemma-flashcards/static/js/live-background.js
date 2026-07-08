(function () {
  const canvas = document.getElementById("liveBackground")
  if (!canvas) return

  const configEl = document.getElementById("liveBackgroundConfig")
  const config = configEl ? JSON.parse(configEl.textContent || "{}") : {}
  const palette = config.palette || {}
  const glyphs = Array.isArray(config.glyphs) && config.glyphs.length ? config.glyphs : ["★", "✦", "☆"]
  const topics = Array.isArray(config.topics) ? config.topics : []
  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches

  const ctx = canvas.getContext("2d")
  let width = 0
  let height = 0
  let particles = []
  let blobs = []
  let frameId = null

  function rand(min, max) {
    return min + Math.random() * (max - min)
  }

  function resize() {
    width = window.innerWidth
    height = window.innerHeight
    canvas.width = width
    canvas.height = height
    initScene()
  }

  function initScene() {
    particles = []
    blobs = [
      {
        x: width * 0.18,
        y: height * 0.22,
        r: Math.max(width, height) * 0.22,
        color: palette.blob1 || "#fff59d",
        dx: 0.08,
        dy: 0.06,
      },
      {
        x: width * 0.78,
        y: height * 0.68,
        r: Math.max(width, height) * 0.18,
        color: palette.blob2 || "#fce8e8",
        dx: -0.06,
        dy: -0.05,
      },
      {
        x: width * 0.52,
        y: height * 0.42,
        r: Math.max(width, height) * 0.12,
        color: palette.blob1 || "#fff59d",
        dx: 0.04,
        dy: 0.07,
      },
    ]

    const count = reducedMotion ? 10 : Math.min(26, 12 + topics.length * 2)
    for (let i = 0; i < count; i += 1) {
      const isStar = i % 3 === 0
      particles.push({
        x: rand(0, width),
        y: rand(0, height),
        size: isStar ? rand(10, 18) : rand(14, 24),
        glyph: isStar ? "★" : glyphs[i % glyphs.length],
        alpha: rand(0.12, 0.28),
        speed: rand(0.08, 0.22),
        drift: rand(-0.12, 0.12),
        phase: rand(0, Math.PI * 2),
      })
    }
  }

  function drawBase() {
    const gradient = ctx.createLinearGradient(0, 0, 0, height)
    gradient.addColorStop(0, "#fff8f8")
    gradient.addColorStop(1, "#fff5f5")
    ctx.fillStyle = gradient
    ctx.fillRect(0, 0, width, height)
  }

  function drawBlobs(time) {
    for (const blob of blobs) {
      if (!reducedMotion) {
        blob.x += blob.dx
        blob.y += blob.dy
        if (blob.x < -blob.r * 0.4 || blob.x > width + blob.r * 0.4) blob.dx *= -1
        if (blob.y < -blob.r * 0.4 || blob.y > height + blob.r * 0.4) blob.dy *= -1
      }

      const pulse = reducedMotion ? 1 : 1 + Math.sin(time * 0.0004 + blob.x * 0.002) * 0.04
      const radius = blob.r * pulse
      const radial = ctx.createRadialGradient(blob.x, blob.y, 0, blob.x, blob.y, radius)
      radial.addColorStop(0, blob.color + "55")
      radial.addColorStop(0.55, blob.color + "22")
      radial.addColorStop(1, blob.color + "00")
      ctx.fillStyle = radial
      ctx.beginPath()
      ctx.arc(blob.x, blob.y, radius, 0, Math.PI * 2)
      ctx.fill()
    }
  }

  function drawParticles(time) {
    ctx.textAlign = "center"
    ctx.textBaseline = "middle"
    for (const particle of particles) {
      if (!reducedMotion) {
        particle.y -= particle.speed
        particle.x += particle.drift + Math.sin(time * 0.001 + particle.phase) * 0.08
        if (particle.y < -30) {
          particle.y = height + 30
          particle.x = rand(0, width)
        }
      }

      ctx.globalAlpha = particle.alpha
      ctx.fillStyle = palette.glyph || "#ffd54f"
      ctx.font = `${particle.size}px Inter, ui-sans-serif, system-ui, sans-serif`
      ctx.fillText(particle.glyph, particle.x, particle.y)
    }
    ctx.globalAlpha = 1
  }

  function drawTopicRibbon() {
    if (!topics.length) return

    const label = topics.slice(0, 3).join(" · ")
    ctx.save()
    ctx.globalAlpha = 0.14
    ctx.fillStyle = palette.glyph || "#e89191"
    ctx.font = "600 13px Inter, ui-sans-serif, system-ui, sans-serif"
    ctx.textAlign = "left"
    ctx.textBaseline = "bottom"
    ctx.fillText(label, 24, height - 18)
    ctx.restore()
  }

  function frame(time) {
    drawBase()
    drawBlobs(time)
    drawParticles(time)
    drawTopicRibbon()
    if (!reducedMotion) {
      frameId = window.requestAnimationFrame(frame)
    }
  }

  resize()
  window.addEventListener("resize", resize)
  frame(0)

  window.addEventListener("beforeunload", () => {
    if (frameId) window.cancelAnimationFrame(frameId)
  })
})()
