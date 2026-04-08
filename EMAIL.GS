function enviarEmailsPendentes() {
  const ss = SpreadsheetApp.getActive();
  const sheet = ss.getSheetByName("Página6"); // Nome da aba atualizado
  
  if (!sheet) {
    console.error("A aba 'Página6' não foi encontrada.");
    return;
  }

  const data = sheet.getDataRange().getValues();
  const rows = data.slice(1); // Ignora o cabeçalho (linha 1)
  
  let listaOrdens = "";
  let destinatarios = new Set();

  rows.forEach(row => {
    let ordem = row[4]; // Coluna E (índice 4)
    let email = row[5]; // Coluna F (índice 5)
    
    // Verifica se a célula da ordem não está vazia
    if (ordem && ordem.toString().trim() !== "") {
      listaOrdens += "- " + ordem + "\n";
    }
    
    // Adiciona o e-mail à lista de envio se ele existir
    if (email && email.toString().trim() !== "" && email.includes("@")) {
      destinatarios.add(email.toString().trim());
    }
  });

  if (listaOrdens !== "" && destinatarios.size > 0) {
    const assunto = "PDF pendente Marfim Bahia";
    const corpo = "Bom dia!\n\n" +
                  "Segue lista de Ordens de Compra sem lançamento de PDF para identificação da marca:\n\n" +
                  listaOrdens + "\n\n" +
                  "Atenciosamente,\n" +
                  "Controle de Prazos e Rotinas Marfim.";
    
    const listaEmails = Array.from(destinatarios).join(",");
    
    MailApp.sendEmail(listaEmails, assunto, corpo);
    console.log("E-mail enviado com sucesso para: " + listaEmails);
  } else {
    console.log("Nenhuma ordem encontrada ou lista de e-mails vazia.");
  }
}
