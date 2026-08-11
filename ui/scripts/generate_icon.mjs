import { mkdir, readFile, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import sharp from 'sharp'
import pngToIco from 'png-to-ico'

const rootDir = resolve(process.cwd(), '..')
const svgPath = resolve(process.cwd(), 'public', 'assets', 'gigsetup-white-full.svg')
const assetsDir = resolve(rootDir, 'assets')
const pngPath = resolve(assetsDir, 'dj_launcher.png')
const icoPath = resolve(assetsDir, 'dj_launcher.ico')

async function main() {
  await mkdir(assetsDir, { recursive: true })

  const svgBuffer = await readFile(svgPath)
  const pngBuffer = await sharp(svgBuffer)
    .resize(512, 512, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 1 } })
    .png()
    .toBuffer()

  await writeFile(pngPath, pngBuffer)

  const icoBuffer = await pngToIco(pngBuffer)
  await writeFile(icoPath, icoBuffer)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
