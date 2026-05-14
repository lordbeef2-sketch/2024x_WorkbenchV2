package com.twcworkbench.cameo.ui;

import javax.swing.BorderFactory;
import javax.swing.JButton;
import javax.swing.JDialog;
import javax.swing.JPanel;
import javax.swing.JProgressBar;
import javax.swing.JScrollPane;
import javax.swing.JTextArea;
import javax.swing.SwingUtilities;
import java.awt.BorderLayout;
import java.awt.Dialog;
import java.awt.Frame;

public class PluginProgressDialog {
    private final JDialog dialog;
    private final JTextArea messageArea;
    private final JProgressBar progressBar;
    private final JButton closeButton;

    public PluginProgressDialog(Frame owner, String title) {
        this.dialog = new JDialog(owner, title, Dialog.ModalityType.MODELESS);
        this.messageArea = new JTextArea(10, 68);
        this.progressBar = new JProgressBar();
        this.closeButton = new JButton("Close");

        this.messageArea.setEditable(false);
        this.messageArea.setLineWrap(true);
        this.messageArea.setWrapStyleWord(true);
        this.messageArea.setBorder(BorderFactory.createEmptyBorder(4, 4, 4, 4));

        this.progressBar.setIndeterminate(true);
        this.closeButton.setEnabled(false);
        this.closeButton.addActionListener(event -> dialog.dispose());

        JPanel content = new JPanel(new BorderLayout(8, 8));
        content.setBorder(BorderFactory.createEmptyBorder(12, 12, 12, 12));
        content.add(progressBar, BorderLayout.NORTH);
        content.add(new JScrollPane(messageArea), BorderLayout.CENTER);

        JPanel footer = new JPanel(new BorderLayout());
        footer.add(closeButton, BorderLayout.EAST);
        content.add(footer, BorderLayout.SOUTH);

        dialog.setContentPane(content);
        dialog.pack();
        dialog.setLocationRelativeTo(owner);
        dialog.setDefaultCloseOperation(JDialog.DO_NOTHING_ON_CLOSE);
    }

    public void showDialog() {
        SwingUtilities.invokeLater(() -> dialog.setVisible(true));
    }

    public void appendMessage(String message) {
        SwingUtilities.invokeLater(() -> {
            if (messageArea.getText().isEmpty()) {
                messageArea.setText(message);
            }
            else {
                messageArea.append(System.lineSeparator());
                messageArea.append(message);
            }
            messageArea.setCaretPosition(messageArea.getDocument().getLength());
        });
    }

    public void markSuccess(String message) {
        SwingUtilities.invokeLater(() -> {
            progressBar.setIndeterminate(false);
            progressBar.setValue(progressBar.getMaximum());
            appendTerminalMessage(message);
            closeButton.setEnabled(true);
            dialog.setDefaultCloseOperation(JDialog.DISPOSE_ON_CLOSE);
        });
    }

    public void markFailure(String message) {
        SwingUtilities.invokeLater(() -> {
            progressBar.setIndeterminate(false);
            progressBar.setValue(0);
            appendTerminalMessage(message);
            closeButton.setEnabled(true);
            dialog.setDefaultCloseOperation(JDialog.DISPOSE_ON_CLOSE);
        });
    }

    private void appendTerminalMessage(String message) {
        if (messageArea.getText().isEmpty()) {
            messageArea.setText(message);
        }
        else {
            messageArea.append(System.lineSeparator());
            messageArea.append(message);
        }
        messageArea.setCaretPosition(messageArea.getDocument().getLength());
    }
}
