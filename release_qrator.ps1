Param(
  [string]$CommitMessage = "release: bump version and build zip"
)

$ErrorActionPreference = "Stop"

# --- config ---
$PluginDir = "qrator"
$Metadata  = Join-Path $PluginDir "metadata.txt"

function Read-Version {
  if (-not (Test-Path $Metadata)) { throw "metadata.txt introuvable: $Metadata" }
  $line = (Get-Content $Metadata | Where-Object { $_ -match '^\s*version\s*=' } | Select-Object -First 1)
  if (-not $line) { throw "Impossible de lire 'version=' dans metadata.txt" }
  return ($line -replace '^\s*version\s*=\s*','').Trim()
}

function Clean-PyCache {
  Write-Host "Nettoyage des __pycache__ et *.pyc …"
  Get-ChildItem -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
  Get-ChildItem -Recurse -Include *.pyc,*.pyo | Remove-Item -Force -ErrorAction SilentlyContinue
}

function Build-Zip {
  param([string]$Version)
  $ZipName = "qrator-$Version.zip"
  if (Test-Path $ZipName) { Remove-Item $ZipName -Force }
  Write-Host "Création de l’archive $ZipName …"

  # On veut un zip qui contient le dossier 'qrator/' à la racine
  # Compress-Archive ne gère pas facilement les exclusions, on nettoie avant (déjà fait)
  Compress-Archive -Path $PluginDir -DestinationPath $ZipName

  if (-not (Test-Path $ZipName)) { throw "Échec de création de $ZipName" }
  return $ZipName
}

function Git-Stage-Commit-Tag-Push {
  param([string]$Version, [string]$ZipName, [string]$Msg)

  Write-Host "Git add …"
  git add -A

  Write-Host "Git commit …"
  try {
    git commit -m $Msg
  } catch {
    Write-Host "Aucun changement à committer, on continue …"
  }

  Write-Host "Git tag v$Version …"
  # si le tag existe déjà, on le remplace (force) sinon on le crée
  $tagExists = (git tag --list "v$Version")
  if ($tagExists) {
    git tag -d "v$Version" | Out-Null
  }
  git tag -a "v$Version" -m "Release v$Version"

  Write-Host "Git push …"
  git push

  Write-Host "Git push tag …"
  git push origin "v$Version"

  Write-Host "OK. Archive prête: $ZipName"
}

# --- run ---
Set-Location -Path (Split-Path -Path $MyInvocation.MyCommand.Path -Parent)

if (-not (Test-Path ".git")) { throw "Ce script doit être lancé à la racine du dépôt (où se trouve .git/)." }
if (-not (Test-Path $PluginDir)) { throw "Dossier plugin '$PluginDir' introuvable à la racine du dépôt." }

$version = Read-Version
Clean-PyCache
$zip = Build-Zip -Version $version
Git-Stage-Commit-Tag-Push -Version $version -ZipName $zip -Msg $CommitMessage

Write-Host ""
Write-Host "🎉 Terminé. Uploade maintenant '$zip' sur plugins.qgis.org → Add new plugin version."