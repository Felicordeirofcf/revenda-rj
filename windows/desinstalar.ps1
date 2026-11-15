# Remove o agendamento do Robô de Revenda RJ (não apaga arquivos).
Unregister-ScheduledTask -TaskName "Revenda RJ" -Confirm:$false
Write-Host "Agendamento 'Revenda RJ' removido."
