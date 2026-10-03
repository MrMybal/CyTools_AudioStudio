# Derive application icons from assets/branding/logo.png.
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Drawing
$branding = Join-Path $PSScriptRoot 'assets/branding'
$settings = Join-Path $PSScriptRoot 'assets/app_settings'
New-Item -ItemType Directory -Force -Path $settings | Out-Null
$source = [System.Drawing.Bitmap]::new((Join-Path $branding 'logo.png'))
$images = @()
try {
    foreach ($size in @(16,24,32,48,64,128,256)) {
        $bitmap = [System.Drawing.Bitmap]::new($size,$size,[System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        $stream = [System.IO.MemoryStream]::new()
        try {
            $graphics.CompositingMode = [System.Drawing.Drawing2D.CompositingMode]::SourceCopy
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
            $graphics.DrawImage($source,[System.Drawing.Rectangle]::new(0,0,$size,$size))
            $bitmap.Save($stream,[System.Drawing.Imaging.ImageFormat]::Png)
            $images += @{Size=$size;Data=$stream.ToArray()}
            if ($size -eq 256) {$bitmap.Save((Join-Path $settings 'icon.png'),[System.Drawing.Imaging.ImageFormat]::Png)}
        } finally {$graphics.Dispose();$stream.Dispose();$bitmap.Dispose()}
    }
} finally {$source.Dispose()}
$file = [System.IO.File]::Create((Join-Path $branding 'logo.ico'))
$writer = [System.IO.BinaryWriter]::new($file)
try {
    $writer.Write([uint16]0);$writer.Write([uint16]1);$writer.Write([uint16]$images.Count)
    $offset = 6 + 16 * $images.Count
    foreach ($image in $images) {
        $dimension = if ($image.Size -eq 256) {0} else {$image.Size}
        $writer.Write([byte]$dimension);$writer.Write([byte]$dimension)
        $writer.Write([byte]0);$writer.Write([byte]0)
        $writer.Write([uint16]1);$writer.Write([uint16]32)
        $writer.Write([uint32]$image.Data.Length);$writer.Write([uint32]$offset)
        $offset += $image.Data.Length
    }
    foreach ($image in $images) {$writer.Write([byte[]]$image.Data)}
} finally {$writer.Dispose();$file.Dispose()}
