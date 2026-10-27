$a = [System.Reflection.Assembly]::LoadFile('C:\Users\qiwai\AppData\Local\Programs\CrossPet\CrossPet.exe')
foreach ($t in $a.GetTypes()) {
    Write-Output $t.FullName
    foreach ($m in $t.GetMethods([System.Reflection.BindingFlags]'Public,NonPublic,Instance,Static')) {
        Write-Output ("  " + $m.Name)
    }
}
