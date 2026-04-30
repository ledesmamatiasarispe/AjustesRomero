using System;
using System.ComponentModel;
using System.Data;
using System.Data.SQLite;
using System.Drawing;
using System.Windows.Forms;
using CarbomaxDelta.Data;

namespace CarbomaxDelta;

public class frmDados : Form
{
	private IContainer components;

	private DataGridView grdDataCab;

	private DataSet dsDados;

	private Button btnDelete;

	private Button btnFechar;

	private Panel panel1;

	private Label label1;

	public frmDados()
	{
		InitializeComponent();
	}

	private void frmDados_Load(object sender, EventArgs e)
	{
		SQLiteConnection connection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand cmd = new SQLiteCommand("SELECT modelo AS Modelo, id AS ID, ip AS IP, modo AS Modo, material AS Material, lote AS Lote, observacao AS Observação, DtInicio AS 'Data Início', DtTermino AS 'Data Término' FROM Analise", connection);
		if (btnDelete.Text != "Excluir")
		{
			cmd = new SQLiteCommand("SELECT modelo AS Model, id AS ID, ip AS IP, modo AS Mod, material AS Material, lote AS Lot, observacao AS Observation, DtInicio AS 'Start Date', DtTermino AS 'Stop Date' FROM Analise", connection);
		}
		SQLiteDataAdapter sQLiteDataAdapter = new SQLiteDataAdapter(cmd);
		new SQLiteCommandBuilder(sQLiteDataAdapter);
		DataTable dataTable = new DataTable();
		sQLiteDataAdapter.Fill(dataTable);
		BindingSource bindingSource = new BindingSource();
		bindingSource.DataSource = dataTable;
		grdDataCab.DataSource = bindingSource;
	}

	private void grdDataCab_UserDeletingRow(object sender, DataGridViewRowCancelEventArgs e)
	{
	}

	private void button1_Click(object sender, EventArgs e)
	{
		if (grdDataCab.SelectedRows.Count == 0 || MessageBox.Show("Confirma a exclusão dos registros selecionados?", "Exclusão de Dados!", MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes)
		{
			return;
		}
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand(sQLiteConnection);
		SQLiteCommand sQLiteCommand2 = new SQLiteCommand(sQLiteConnection);
		sQLiteConnection.Open();
		foreach (DataGridViewRow selectedRow in grdDataCab.SelectedRows)
		{
			sQLiteCommand.CommandText = "DELETE FROM Analise WHERE id = '" + selectedRow.Cells["id"].Value.ToString() + "'";
			sQLiteCommand2.CommandText = "DELETE FROM AnaliseItens WHERE id_Analise = '" + selectedRow.Cells["id"].Value.ToString() + "'";
			sQLiteCommand.ExecuteNonQuery();
			sQLiteCommand2.ExecuteNonQuery();
			sQLiteCommand.ExecuteNonQuery();
			grdDataCab.Rows.RemoveAt(selectedRow.Index);
		}
		sQLiteConnection.Close();
	}

	private void panel1_Paint(object sender, PaintEventArgs e)
	{
	}

	private void btnFechar_Click(object sender, EventArgs e)
	{
		Close();
	}

	protected override void Dispose(bool disposing)
	{
		if (disposing && components != null)
		{
			components.Dispose();
		}
		base.Dispose(disposing);
	}

	private void InitializeComponent()
	{
		System.ComponentModel.ComponentResourceManager componentResourceManager = new System.ComponentModel.ComponentResourceManager(typeof(CarbomaxDelta.frmDados));
		this.grdDataCab = new System.Windows.Forms.DataGridView();
		this.dsDados = new System.Data.DataSet();
		this.btnDelete = new System.Windows.Forms.Button();
		this.btnFechar = new System.Windows.Forms.Button();
		this.panel1 = new System.Windows.Forms.Panel();
		this.label1 = new System.Windows.Forms.Label();
		((System.ComponentModel.ISupportInitialize)this.grdDataCab).BeginInit();
		((System.ComponentModel.ISupportInitialize)this.dsDados).BeginInit();
		this.panel1.SuspendLayout();
		base.SuspendLayout();
		this.grdDataCab.AllowUserToAddRows = false;
		this.grdDataCab.AllowUserToDeleteRows = false;
		this.grdDataCab.AllowUserToOrderColumns = true;
		componentResourceManager.ApplyResources(this.grdDataCab, "grdDataCab");
		this.grdDataCab.ColumnHeadersHeightSizeMode = System.Windows.Forms.DataGridViewColumnHeadersHeightSizeMode.AutoSize;
		this.grdDataCab.Name = "grdDataCab";
		this.grdDataCab.ReadOnly = true;
		this.grdDataCab.SelectionMode = System.Windows.Forms.DataGridViewSelectionMode.FullRowSelect;
		this.grdDataCab.UserDeletingRow += new System.Windows.Forms.DataGridViewRowCancelEventHandler(grdDataCab_UserDeletingRow);
		this.dsDados.DataSetName = "dsDados";
		componentResourceManager.ApplyResources(this.btnDelete, "btnDelete");
		this.btnDelete.Name = "btnDelete";
		this.btnDelete.UseVisualStyleBackColor = true;
		this.btnDelete.Click += new System.EventHandler(button1_Click);
		componentResourceManager.ApplyResources(this.btnFechar, "btnFechar");
		this.btnFechar.Name = "btnFechar";
		this.btnFechar.UseVisualStyleBackColor = true;
		this.btnFechar.Click += new System.EventHandler(btnFechar_Click);
		this.panel1.BackColor = System.Drawing.SystemColors.ActiveCaption;
		this.panel1.Controls.Add(this.label1);
		componentResourceManager.ApplyResources(this.panel1, "panel1");
		this.panel1.Name = "panel1";
		componentResourceManager.ApplyResources(this.label1, "label1");
		this.label1.Name = "label1";
		componentResourceManager.ApplyResources(this, "$this");
		base.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
		base.Controls.Add(this.panel1);
		base.Controls.Add(this.btnFechar);
		base.Controls.Add(this.btnDelete);
		base.Controls.Add(this.grdDataCab);
		base.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog;
		base.MaximizeBox = false;
		base.MinimizeBox = false;
		base.Name = "frmDados";
		base.Load += new System.EventHandler(frmDados_Load);
		((System.ComponentModel.ISupportInitialize)this.grdDataCab).EndInit();
		((System.ComponentModel.ISupportInitialize)this.dsDados).EndInit();
		this.panel1.ResumeLayout(false);
		this.panel1.PerformLayout();
		base.ResumeLayout(false);
	}
}
