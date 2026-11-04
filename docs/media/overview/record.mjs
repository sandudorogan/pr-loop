// Renders index.html frame by frame into ../overview.mp4 and the README preview ../overview.gif.
// Needs ffmpeg and playwright-core: bun add --no-save playwright-core@1.58.0 && bun record.mjs
import { spawn, spawnSync } from 'node:child_process'
import { chromium } from 'playwright-core'

const FPS = 30
const here = new URL('.', import.meta.url)
const out = name => new URL(`../${name}`, here).pathname

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1280, height: 720 }, deviceScaleFactor: 1.5 })
await page.goto(new URL('index.html', here).href)
const duration = await page.evaluate('DURATION')

const ffmpeg = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-f', 'image2pipe', '-framerate', `${FPS}`, '-i', '-',
  '-c:v', 'libx264', '-preset', 'slow', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out('overview.mp4')],
  { stdio: ['pipe', 'inherit', 'inherit'] })

for (let frame = 0; frame < duration * FPS; frame++) {
  await page.evaluate(t => render(t), frame / FPS)
  ffmpeg.stdin.write(await page.screenshot())
}
ffmpeg.stdin.end()
await new Promise(done => ffmpeg.on('close', done))
await browser.close()

spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', out('overview.mp4'), '-filter_complex',
  'fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=diff[p];[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle',
  out('overview.gif')], { stdio: 'inherit' })
