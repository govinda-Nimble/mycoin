import docx

doc = docx.Document()
doc.add_heading('MYCOIN Architecture Test', level=0)
doc.add_paragraph('Test paragraph verified with python-docx.')
doc.save('test_python_docx.docx')
print("Saved test_python_docx.docx successfully.")
