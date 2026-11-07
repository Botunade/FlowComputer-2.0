# PowerShell Text-to-Speech using Windows SAPI
param(
    [Parameter(Mandatory=$true)]
    [string]$Text,

    [string]$OutputFile = "speech.wav"
)

Add-Type -AssemblyName System.Speech

$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer

# Save audio to file
$speak.SetOutputToWaveFile($OutputFile)
$speak.Speak($Text)

Write-Host "Audio saved to: $OutputFile"
Write-Host "Text spoken: $Text"

# Clean up
$speak.Dispose()