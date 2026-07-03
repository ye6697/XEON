$ErrorActionPreference = "Stop"

$VideoPath = "C:\Users\User\Downloads\Intro Video XEON.mp4"
$StartSeconds = 36
$DurationSeconds = 6

if (-not (Test-Path -LiteralPath $VideoPath)) {
    exit 0
}

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

$window = New-Object System.Windows.Window
$window.WindowStyle = [System.Windows.WindowStyle]::None
$window.ResizeMode = [System.Windows.ResizeMode]::NoResize
$window.WindowState = [System.Windows.WindowState]::Maximized
$window.Topmost = $true
$window.Background = [System.Windows.Media.Brushes]::Black
$window.ShowInTaskbar = $false

$media = New-Object System.Windows.Controls.MediaElement
$media.LoadedBehavior = [System.Windows.Controls.MediaState]::Manual
$media.UnloadedBehavior = [System.Windows.Controls.MediaState]::Stop
$media.Stretch = [System.Windows.Media.Stretch]::UniformToFill
$media.Source = [Uri]::new($VideoPath)
$window.Content = $media

$closeTimer = New-Object System.Windows.Threading.DispatcherTimer
$closeTimer.Interval = [TimeSpan]::FromSeconds($DurationSeconds)
$closeTimer.Add_Tick({
    $closeTimer.Stop()
    $media.Stop()
    $window.Close()
})

$window.Add_KeyDown({
    param($sender, $eventArgs)
    if ($eventArgs.Key -eq [System.Windows.Input.Key]::Escape) {
        $closeTimer.Stop()
        $media.Stop()
        $window.Close()
    }
})

$media.Add_MediaOpened({
    $media.Position = [TimeSpan]::FromSeconds($StartSeconds)
    $media.Play()
    $closeTimer.Start()
})

$media.Add_MediaFailed({
    $closeTimer.Stop()
    $window.Close()
})

$null = $window.ShowDialog()
