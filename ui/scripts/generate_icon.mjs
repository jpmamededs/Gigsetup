import { mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import sharp from 'sharp'
import pngToIco from 'png-to-ico'

const execFileAsync = promisify(execFile)

const rootDir = resolve(process.cwd(), '..')
const svgPath = resolve(process.cwd(), 'public', 'assets', 'gigsetup-white-full.svg')
const assetsDir = resolve(rootDir, 'assets')
const pngPath = resolve(assetsDir, 'dj_launcher.png')
const icoPath = resolve(assetsDir, 'dj_launcher.ico')
const icnsPath = resolve(assetsDir, 'dj_launcher.icns')
const iconsetDir = resolve(assetsDir, 'dj_launcher.iconset')

// ponytail: sizes required by iconutil for a complete .iconset, no more
const iconsetSizes = [
  ['icon_16x16.png', 16],
  ['icon_16x16@2x.png', 32],
  ['icon_32x32.png', 32],
  ['icon_32x32@2x.png', 64],
  ['icon_128x128.png', 128],
  ['icon_128x128@2x.png', 256],
  ['icon_256x256.png', 256],
  ['icon_256x256@2x.png', 512],
  ['icon_512x512.png', 512],
  ['icon_512x512@2x.png', 1024],
]

async function generateIcns(svgBuffer) {
  if (process.platform !== 'darwin') {
    console.log('skipping .icns generation: not macOS')
    return
  }

  await mkdir(iconsetDir, { recursive: true })

  await Promise.all(
    iconsetSizes.map(async ([name, size]) => {
      const buffer = await sharp(svgBuffer)
        .resize(size, size, { fit: 'contain', background: { r: 0, g: 0, b: 0, alpha: 1 } })
        .png()
        .toBuffer()
      await writeFile(resolve(iconsetDir, name), buffer)
    })
  )

  await execFileAsync('iconutil', ['-c', 'icns', iconsetDir, '-o', icnsPath])
  await rm(iconsetDir, { recursive: true, force: true })
}

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

  await generateIcns(svgBuffer)
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})
