using System;
using System.ComponentModel;
using System.Data;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Reporting.WinForms;

namespace CarbomaxDelta;

public class frmReport002 : Form
{
	public DataSet dsCab = new DataSet("dsCab");

	private string pdf = "";

	private IContainer components;

	public ReportViewer rptViewer;

	public frmReport002()
	{
		InitializeComponent();
	}

	private bool generatePDF()
	{
		try
		{
			string mimeType = string.Empty;
			string encoding = string.Empty;
			string fileNameExtension = string.Empty;
			string[] streams;
			Warning[] warnings;
			byte[] array = rptViewer.LocalReport.Render("PDF", null, out mimeType, out encoding, out fileNameExtension, out streams, out warnings);
			using (FileStream fileStream = new FileStream(pdf, FileMode.Create))
			{
				for (int i = 0; i < array.Length; i++)
				{
					fileStream.WriteByte(array[i]);
				}
				fileStream.Seek(0L, SeekOrigin.Begin);
				for (int j = 0; j < fileStream.Length; j++)
				{
					if (array[j] != fileStream.ReadByte())
					{
						Console.WriteLine("Error writing data.");
						return false;
					}
				}
			}
			return true;
		}
		catch (Exception ex)
		{
			MessageBox.Show(ex.Message, "generatePDF");
			return false;
		}
	}

	private void frmReportPreview_Load(object sender, EventArgs e)
	{
		try
		{
			rptViewer.ProcessingMode = ProcessingMode.Local;
			rptViewer.LocalReport.DataSources.Clear();
			ReportDataSource item = new ReportDataSource("dsCab", dsCab.Tables[0]);
			rptViewer.LocalReport.DataSources.Add(item);
			rptViewer.SetDisplayMode(DisplayMode.PrintLayout);
			pdf = Path.GetTempPath() + "CarboMaxDelta_Table.pdf";
			if (generatePDF())
			{
				Process.Start(pdf);
				Close();
			}
		}
		catch (ReportViewerException ex)
		{
			MessageBox.Show(ex.Message);
		}
		catch (Exception ex2)
		{
			MessageBox.Show(ex2.Message);
		}
	}

	private void reportViewer1_ReportError(object sender, ReportErrorEventArgs e)
	{
		MessageBox.Show(e.Exception.Message);
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
		this.rptViewer = new Microsoft.Reporting.WinForms.ReportViewer();
		base.SuspendLayout();
		this.rptViewer.Dock = System.Windows.Forms.DockStyle.Fill;
		this.rptViewer.LocalReport.ReportPath = "";
		this.rptViewer.Location = new System.Drawing.Point(0, 0);
		this.rptViewer.Name = "rptViewer";
		this.rptViewer.ShowRefreshButton = false;
		this.rptViewer.Size = new System.Drawing.Size(601, 433);
		this.rptViewer.TabIndex = 2;
		base.AutoScaleDimensions = new System.Drawing.SizeF(6f, 13f);
		base.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
		base.ClientSize = new System.Drawing.Size(601, 433);
		base.Controls.Add(this.rptViewer);
		base.Name = "frmReport002";
		base.StartPosition = System.Windows.Forms.FormStartPosition.CenterScreen;
		this.Text = "Report Preview Table";
		base.WindowState = System.Windows.Forms.FormWindowState.Maximized;
		base.Load += new System.EventHandler(frmReportPreview_Load);
		base.ResumeLayout(false);
	}
}
