param(
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\ShengaoKaraoke-0.7.0'),
    [switch]$NoShortcuts
)
$ErrorActionPreference = 'Stop'
$packageRoot = $PSScriptRoot
$executable = Join-Path $packageRoot 'shengao-karaoke.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) { throw '请从完整解压后的软件包运行安装。' }
$target = [System.IO.Path]::GetFullPath($Destination)
if ($target -eq [System.IO.Path]::GetPathRoot($target) -or $target -eq $packageRoot -or $target.StartsWith($packageRoot + '\', [StringComparison]::OrdinalIgnoreCase)) { throw '安装目录无效。' }
if (Test-Path -LiteralPath $target) { throw '安装目录已存在。请选择一个新的空目录，或直接运行已有软件。' }
New-Item -ItemType Directory -Path $target | Out-Null
foreach ($item in Get-ChildItem -LiteralPath $packageRoot) {
    Copy-Item -LiteralPath $item.FullName -Destination $target -Recurse
}
if (-not $NoShortcuts) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Programs')) '声稿 Karaoke Studio.lnk'))
    $shortcut.TargetPath = Join-Path $target 'shengao-karaoke.exe'
    $shortcut.WorkingDirectory = $target
    $shortcut.Description = '日语歌词打轴、注音与卡拉 OK 字幕制作'
    $shortcut.Save()
}
Write-Host ('安装完成：' + $target)
Write-Host '可从开始菜单启动；密钥与设置保存在当前用户目录。'
