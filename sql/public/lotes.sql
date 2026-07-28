-- Contrato de consumo dos lotes de ingresso (lidos pelo detalhar_evento, e
-- portanto pelo site e pelo MCP).
--
-- `lotes` é 100% derivada do cru e a derivação já a apaga e reinsere inteira a
-- cada rodada: é prata por definição, e por isso mora em `tratado`. Ser
-- consumida não define a camada; **ser reconstruível define**. O consumo
-- atravessa a fronteira por esta view.
--
-- 1:1 com a tabela — o desacoplamento existe para quando for preciso, não
-- porque já é preciso.

CREATE OR REPLACE VIEW public.lotes AS
SELECT evento_id, ordem, nome, preco, taxa, gratis, esgotado
FROM tratado.lotes;
