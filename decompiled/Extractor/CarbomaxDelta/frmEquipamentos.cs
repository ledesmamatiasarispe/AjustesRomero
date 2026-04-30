using System;
using System.ComponentModel;
using System.Data;
using System.Data.SQLite;
using System.Drawing;
using System.Globalization;
using System.Net;
using System.Threading;
using System.Windows.Forms;
using CarbomaxDelta.Data;
using CarbomaxDelta.Properties;

namespace CarbomaxDelta;

public class frmEquipamentos : Form
{
	private bool isNew;

	private IContainer components;

	private DataGridView grdLista;

	private ToolStrip toolStrip1;

	private ToolStripButton btnNovo;

	private ToolStripButton btnAlterar;

	private ToolStripButton btnExcluir;

	private ToolStripSeparator toolStripSeparator1;

	private ToolStripButton btnConfirma;

	private ToolStripButton btnCancela;

	private ToolStripSeparator toolStripSeparator2;

	private ToolStripButton btnSair;

	private Label label1;

	private TextBox txtID;

	private TextBox txtDescricao;

	private Label label2;

	private Label label3;

	private TextBox txtIP;

	private DataGridViewTextBoxColumn colID;

	private DataGridViewTextBoxColumn colDesc;

	private DataGridViewTextBoxColumn colIP;

	public frmEquipamentos()
	{
		InitializeComponent();
	}

	private void btnSair_Click(object sender, EventArgs e)
	{
		Close();
	}

	private void frmEquipamentos_Load(object sender, EventArgs e)
	{
		grdLista.AutoGenerateColumns = false;
		AtualizaLista();
	}

	private void AtualizaLista()
	{
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("SELECT * FROM Equipamento", sQLiteConnection);
		try
		{
			sQLiteConnection.Open();
			DataTable dataTable = new DataTable("Equipamento");
			dataTable.Load(sQLiteCommand.ExecuteReader());
			sQLiteConnection.Close();
			grdLista.DataSource = dataTable;
		}
		catch (SQLiteException ex)
		{
			MessageBox.Show(ex.Message);
		}
	}

	private void btnNovo_Click(object sender, EventArgs e)
	{
		isNew = true;
		txtDescricao.ReadOnly = false;
		txtIP.ReadOnly = false;
		txtDescricao.Text = "";
		txtIP.Text = "";
		txtID.Text = "0";
		txtDescricao.Focus();
		setState(pEditar: true);
	}

	private void setState(bool pEditar)
	{
		btnAlterar.Enabled = !pEditar;
		btnCancela.Enabled = pEditar;
		btnConfirma.Enabled = pEditar;
		btnExcluir.Enabled = !pEditar;
		btnNovo.Enabled = !pEditar;
		btnSair.Enabled = !pEditar;
		grdLista.Enabled = !pEditar;
	}

	private void btnAlterar_Click(object sender, EventArgs e)
	{
		if (grdLista.RowCount != 0)
		{
			isNew = false;
			txtDescricao.ReadOnly = false;
			txtIP.ReadOnly = false;
			txtDescricao.Focus();
			setState(pEditar: true);
		}
	}

	private void btnExcluir_Click(object sender, EventArgs e)
	{
		if (grdLista.RowCount == 0 || MessageBox.Show("Excluir este Equipamento?", "CarboxMaxDelta", MessageBoxButtons.YesNo) == DialogResult.No)
		{
			return;
		}
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("DELETE FROM Equipamento WHERE id=@pID", sQLiteConnection);
		SQLiteTransaction sQLiteTransaction = null;
		try
		{
			sQLiteConnection.Open();
			sQLiteTransaction = sQLiteConnection.BeginTransaction();
			sQLiteCommand.Parameters.AddWithValue("@pID", txtID.Text);
			sQLiteCommand.ExecuteNonQuery();
			sQLiteTransaction.Commit();
			sQLiteConnection.Close();
		}
		catch (SQLiteException ex)
		{
			sQLiteTransaction?.Rollback();
			MessageBox.Show(ex.Message);
		}
		catch (Exception ex2)
		{
			sQLiteTransaction?.Rollback();
			MessageBox.Show(ex2.Message);
		}
		finally
		{
			AtualizaLista();
			if (grdLista.RowCount == 0)
			{
				txtIP.Text = "";
				txtDescricao.Text = "";
				txtID.Text = "";
			}
		}
	}

	private void btnConfirma_Click(object sender, EventArgs e)
	{
		IPAddress address = null;
		if (!IPAddress.TryParse(txtIP.Text, out address))
		{
			if (Thread.CurrentThread.CurrentCulture == new CultureInfo("pt-BR"))
			{
				MessageBox.Show("Endereço IP Inválido. Por favor verifique!", "CarboMaxDelta", MessageBoxButtons.OK, MessageBoxIcon.Exclamation);
			}
			else
			{
				MessageBox.Show("Invalid IP Address. Please Verify!", "CarboMaxDelta", MessageBoxButtons.OK, MessageBoxIcon.Exclamation);
			}
			return;
		}
		SQLiteConnection sQLiteConnection = new SQLiteConnection(DbUtils.cnString);
		SQLiteCommand sQLiteCommand = new SQLiteCommand("INSERT INTO Equipamento (Descricao, IP) VALUES(@Descricao, @IP)", sQLiteConnection);
		SQLiteTransaction sQLiteTransaction = null;
		if (!isNew)
		{
			sQLiteCommand.CommandText = "UPDATE Equipamento SET Descricao=@Descricao, IP=@IP WHERE id=@EquipamentoID";
		}
		try
		{
			sQLiteConnection.Open();
			sQLiteTransaction = sQLiteConnection.BeginTransaction();
			sQLiteCommand.Parameters.AddWithValue("@Descricao", txtDescricao.Text.ToUpper());
			sQLiteCommand.Parameters.AddWithValue("@IP", txtIP.Text);
			if (!isNew)
			{
				sQLiteCommand.Parameters.AddWithValue("@EquipamentoID", txtID.Text);
			}
			sQLiteCommand.ExecuteNonQuery();
			sQLiteTransaction.Commit();
			sQLiteConnection.Close();
			setState(pEditar: false);
			txtDescricao.ReadOnly = true;
			txtIP.ReadOnly = true;
		}
		catch (SQLiteException ex)
		{
			sQLiteTransaction?.Rollback();
			MessageBox.Show(ex.Message);
		}
		catch (Exception ex2)
		{
			sQLiteTransaction?.Rollback();
			MessageBox.Show(ex2.Message);
		}
		finally
		{
			AtualizaLista();
		}
	}

	private void btnCancela_Click(object sender, EventArgs e)
	{
		AtualizaLista();
		txtDescricao.ReadOnly = true;
		txtIP.ReadOnly = true;
		setState(pEditar: false);
	}

	private void grdLista_SelectionChanged(object sender, EventArgs e)
	{
		if (grdLista.RowCount > 0 && grdLista.CurrentRow.Cells[0].Value != null)
		{
			txtID.Text = grdLista.CurrentRow.Cells[0].Value.ToString();
			txtDescricao.Text = grdLista.CurrentRow.Cells[1].Value.ToString();
			txtIP.Text = grdLista.CurrentRow.Cells[2].Value.ToString();
		}
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
		System.ComponentModel.ComponentResourceManager resources = new System.ComponentModel.ComponentResourceManager(typeof(CarbomaxDelta.frmEquipamentos));
		this.grdLista = new System.Windows.Forms.DataGridView();
		this.toolStrip1 = new System.Windows.Forms.ToolStrip();
		this.btnNovo = new System.Windows.Forms.ToolStripButton();
		this.btnAlterar = new System.Windows.Forms.ToolStripButton();
		this.btnExcluir = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator1 = new System.Windows.Forms.ToolStripSeparator();
		this.btnConfirma = new System.Windows.Forms.ToolStripButton();
		this.btnCancela = new System.Windows.Forms.ToolStripButton();
		this.toolStripSeparator2 = new System.Windows.Forms.ToolStripSeparator();
		this.btnSair = new System.Windows.Forms.ToolStripButton();
		this.label1 = new System.Windows.Forms.Label();
		this.txtID = new System.Windows.Forms.TextBox();
		this.txtDescricao = new System.Windows.Forms.TextBox();
		this.label2 = new System.Windows.Forms.Label();
		this.label3 = new System.Windows.Forms.Label();
		this.txtIP = new System.Windows.Forms.TextBox();
		this.colID = new System.Windows.Forms.DataGridViewTextBoxColumn();
		this.colDesc = new System.Windows.Forms.DataGridViewTextBoxColumn();
		this.colIP = new System.Windows.Forms.DataGridViewTextBoxColumn();
		((System.ComponentModel.ISupportInitialize)this.grdLista).BeginInit();
		this.toolStrip1.SuspendLayout();
		base.SuspendLayout();
		this.grdLista.AllowUserToAddRows = false;
		this.grdLista.AllowUserToDeleteRows = false;
		this.grdLista.BackgroundColor = System.Drawing.Color.White;
		this.grdLista.ColumnHeadersHeightSizeMode = System.Windows.Forms.DataGridViewColumnHeadersHeightSizeMode.AutoSize;
		this.grdLista.Columns.AddRange(this.colID, this.colDesc, this.colIP);
		resources.ApplyResources(this.grdLista, "grdLista");
		this.grdLista.MultiSelect = false;
		this.grdLista.Name = "grdLista";
		this.grdLista.ReadOnly = true;
		this.grdLista.SelectionChanged += new System.EventHandler(grdLista_SelectionChanged);
		this.toolStrip1.GripStyle = System.Windows.Forms.ToolStripGripStyle.Hidden;
		this.toolStrip1.Items.AddRange(new System.Windows.Forms.ToolStripItem[8] { this.btnNovo, this.btnAlterar, this.btnExcluir, this.toolStripSeparator1, this.btnConfirma, this.btnCancela, this.toolStripSeparator2, this.btnSair });
		resources.ApplyResources(this.toolStrip1, "toolStrip1");
		this.toolStrip1.Name = "toolStrip1";
		this.btnNovo.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btnNovo.Image = CarbomaxDelta.Properties.Resources.im_add;
		resources.ApplyResources(this.btnNovo, "btnNovo");
		this.btnNovo.Name = "btnNovo";
		this.btnNovo.Click += new System.EventHandler(btnNovo_Click);
		this.btnAlterar.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btnAlterar.Image = CarbomaxDelta.Properties.Resources.im_edl;
		resources.ApplyResources(this.btnAlterar, "btnAlterar");
		this.btnAlterar.Name = "btnAlterar";
		this.btnAlterar.Click += new System.EventHandler(btnAlterar_Click);
		this.btnExcluir.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btnExcluir.Image = CarbomaxDelta.Properties.Resources.im_era;
		resources.ApplyResources(this.btnExcluir, "btnExcluir");
		this.btnExcluir.Name = "btnExcluir";
		this.btnExcluir.Click += new System.EventHandler(btnExcluir_Click);
		this.toolStripSeparator1.Name = "toolStripSeparator1";
		resources.ApplyResources(this.toolStripSeparator1, "toolStripSeparator1");
		this.btnConfirma.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		resources.ApplyResources(this.btnConfirma, "btnConfirma");
		this.btnConfirma.Image = CarbomaxDelta.Properties.Resources.im_chck1;
		this.btnConfirma.Name = "btnConfirma";
		this.btnConfirma.Click += new System.EventHandler(btnConfirma_Click);
		this.btnCancela.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		resources.ApplyResources(this.btnCancela, "btnCancela");
		this.btnCancela.Image = CarbomaxDelta.Properties.Resources.im_cancel;
		this.btnCancela.Name = "btnCancela";
		this.btnCancela.Click += new System.EventHandler(btnCancela_Click);
		this.toolStripSeparator2.Name = "toolStripSeparator2";
		resources.ApplyResources(this.toolStripSeparator2, "toolStripSeparator2");
		this.btnSair.DisplayStyle = System.Windows.Forms.ToolStripItemDisplayStyle.Image;
		this.btnSair.Image = CarbomaxDelta.Properties.Resources.im_exi;
		resources.ApplyResources(this.btnSair, "btnSair");
		this.btnSair.Name = "btnSair";
		this.btnSair.Click += new System.EventHandler(btnSair_Click);
		resources.ApplyResources(this.label1, "label1");
		this.label1.Name = "label1";
		resources.ApplyResources(this.txtID, "txtID");
		this.txtID.Name = "txtID";
		this.txtID.ReadOnly = true;
		resources.ApplyResources(this.txtDescricao, "txtDescricao");
		this.txtDescricao.Name = "txtDescricao";
		this.txtDescricao.ReadOnly = true;
		resources.ApplyResources(this.label2, "label2");
		this.label2.Name = "label2";
		resources.ApplyResources(this.label3, "label3");
		this.label3.Name = "label3";
		resources.ApplyResources(this.txtIP, "txtIP");
		this.txtIP.Name = "txtIP";
		this.txtIP.ReadOnly = true;
		this.colID.DataPropertyName = "ID";
		resources.ApplyResources(this.colID, "colID");
		this.colID.Name = "colID";
		this.colID.ReadOnly = true;
		this.colDesc.AutoSizeMode = System.Windows.Forms.DataGridViewAutoSizeColumnMode.Fill;
		this.colDesc.DataPropertyName = "Descricao";
		resources.ApplyResources(this.colDesc, "colDesc");
		this.colDesc.Name = "colDesc";
		this.colDesc.ReadOnly = true;
		this.colIP.DataPropertyName = "IP";
		resources.ApplyResources(this.colIP, "colIP");
		this.colIP.Name = "colIP";
		this.colIP.ReadOnly = true;
		resources.ApplyResources(this, "$this");
		base.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
		base.Controls.Add(this.txtIP);
		base.Controls.Add(this.label3);
		base.Controls.Add(this.txtDescricao);
		base.Controls.Add(this.label2);
		base.Controls.Add(this.txtID);
		base.Controls.Add(this.label1);
		base.Controls.Add(this.toolStrip1);
		base.Controls.Add(this.grdLista);
		base.FormBorderStyle = System.Windows.Forms.FormBorderStyle.FixedDialog;
		base.MaximizeBox = false;
		base.MinimizeBox = false;
		base.Name = "frmEquipamentos";
		base.ShowIcon = false;
		base.ShowInTaskbar = false;
		base.Load += new System.EventHandler(frmEquipamentos_Load);
		((System.ComponentModel.ISupportInitialize)this.grdLista).EndInit();
		this.toolStrip1.ResumeLayout(false);
		this.toolStrip1.PerformLayout();
		base.ResumeLayout(false);
		base.PerformLayout();
	}
}
