"""Generate realistic sample files (made-up people and courses) to try Hop on.

Usage:  python scripts/make_samples.py  [output_dir]
"""
import io
import json
import os
import sys
import zipfile
from email.message import EmailMessage

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "samples")
os.makedirs(OUT, exist_ok=True)


def p(name):
    return os.path.join(OUT, name)


def pdf(name, lines, title_meta=""):
    """lines: (text, size, bold) top to bottom."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    c = canvas.Canvas(p(name), pagesize=A4)
    c.setTitle(title_meta)
    y = 800
    for text, size, bold in lines:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.drawString(50, y, text)
        y -= size + 9
    c.save()


def paper():
    pdf("1706.03762v5.pdf", [
        ("arXiv:1706.03762v5 [cs.CL] 6 Dec 2017", 8, False),
        ("Attention Is All You Need", 20, True),
        ("Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit", 10, False),
        ("Google Brain", 10, False),
        ("Abstract", 12, True),
        ("The dominant sequence transduction models are based on complex recurrent or convolutional", 10, False),
        ("neural networks. We propose a new simple network architecture, the Transformer.", 10, False),
        ("1 Introduction", 12, True),
        ("Recurrent neural networks have been firmly established as state of the art approaches.", 10, False),
        ("2 Related Work", 12, True),
        ("References", 12, True),
        ("[1] Jimmy Lei Ba et al. Layer normalization. arXiv preprint, 2016.", 9, False),
    ])


def assignment():
    pdf("DA3.pdf", [
        ("Vellore Institute of Technology", 11, False),
        ("School of Computer Science and Engineering", 10, False),
        ("Course Code: BCSE202L   Data Structures and Algorithms", 10, False),
        ("Digital Assignment 3", 13, True),
        ("Linked Lists and Stacks", 18, True),
        ("Date: 28.10.2026        Due date: 15.11.2026", 10, False),
        ("Q1. Implement a singly linked list with insert and delete operations. (10 marks)", 10, False),
        ("Q2. Use a stack to check balanced parentheses. (10 marks)", 10, False),
        ("Submit the code and output screenshots on the portal before the deadline.", 10, False),
    ])


def exam():
    pdf("QP.pdf", [
        ("VELLORE INSTITUTE OF TECHNOLOGY", 12, True),
        ("End Semester Examination - Fall Semester 2025-26", 11, False),
        ("Course Code: MAT2002     Course Title: Applications of Differential and Difference Equations", 9, False),
        ("Date of Exam: 19.11.2025      Time: 3 Hours      Max Marks: 100", 10, False),
        ("Answer ALL questions", 10, True),
        ("PART A (10 x 3 = 30 marks)", 10, False),
        ("1. Solve the differential equation y'' + 4y = sin 2x.", 10, False),
    ])


def certificate():
    pdf("certificate.pdf", [
        ("Coursera", 12, False),
        ("CERTIFICATE OF COMPLETION", 22, True),
        ("This is to certify that", 11, False),
        ("Ravi Kumar", 18, True),
        ("has successfully completed", 11, False),
        ("Machine Learning Specialization", 15, True),
        ("an online non-credit course authorized by Stanford University and DeepLearning.AI", 9, False),
        ("Date: September 12, 2026", 10, False),
        ("Credential ID: 8XK2QPL7M4ZA      Verify at coursera.org/verify/8XK2QPL7M4ZA", 9, False),
    ])


def receipt():
    pdf("receipt_1730284112.pdf", [
        ("Spotify", 16, True),
        ("Payment Receipt", 13, True),
        ("Payment successful", 10, False),
        ("Date: 30 Oct 2026", 10, False),
        ("Transaction ID: T2610301198745", 10, False),
        ("Order ID: SP-77812-IN", 10, False),
        ("Spotify Premium Student - 1 month", 10, False),
        ("Amount paid: Rs 59.00 via UPI", 10, False),
    ])


def ticket():
    pdf("ticket.pdf", [
        ("IRCTC  Electronic Reservation Slip (ERS)", 12, True),
        ("E-Ticket", 11, False),
        ("PNR: 4521367890     Train: 12639 Brindavan Express", 10, False),
        ("From: MAS Chennai Central   To: KPD Katpadi Jn", 10, False),
        ("Date of Journey: 12-Nov-2026   Departure: 07:50", 10, False),
        ("Passenger: Ravi Kumar  Age 20  Seat: D4 / 32", 10, False),
        ("Booking Date: 30-Oct-2026", 9, False),
    ])


def slides():
    from pptx import Presentation
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "Lecture 7: Dynamic Programming"
    s.placeholders[1].text = "CS 301 - Design and Analysis of Algorithms\nOctober 2026"
    s2 = prs.slides.add_slide(prs.slide_layouts[1])
    s2.shapes.title.text = "Today's topics"
    s2.placeholders[1].text = "Recap of greedy algorithms\nMemoization vs tabulation\nKnapsack problem"
    prs.core_properties.title = ""
    prs.save(p("lec07.pptx"))


def lab():
    import docx
    d = docx.Document()
    d.add_paragraph("CSE3001 Computer Networks Lab")
    d.add_heading("Experiment No. 5", 1)
    d.add_paragraph("Date: 21/10/2026")
    d.add_paragraph("Aim: To implement a client-server chat using TCP sockets")
    d.add_paragraph("Procedure: 1. Create a server socket. 2. Bind and listen. 3. Accept the client connection.")
    d.add_paragraph("Result: The TCP chat application was implemented and the output was verified.")
    d.save(p("Document1.docx"))


def resume():
    import docx
    d = docx.Document()
    d.add_heading("RAVI KUMAR", 0)
    d.add_paragraph("ravi.kumar@example.com | linkedin.com/in/ravikumar | github.com/ravik")
    d.add_heading("Education", 1)
    d.add_paragraph("B.Tech Computer Science, Vellore Institute of Technology - CGPA 8.9")
    d.add_heading("Technical Skills", 1)
    d.add_paragraph("Python, Java, C++, SQL, React")
    d.add_heading("Projects", 1)
    d.add_paragraph("Hop - smart file renamer (Python, FastAPI)")
    d.save(p("resume_final_v2.docx"))


def code():
    with open(p("main.py"), "w") as f:
        f.write('"""Dijkstra shortest path on a weighted graph."""\nimport heapq\n\n\ndef dijkstra(graph, src):\n'
                '    dist = {v: float("inf") for v in graph}\n    dist[src] = 0\n    pq = [(0, src)]\n    return dist\n')


def notebook():
    nb = {"cells": [
        {"cell_type": "markdown", "metadata": {}, "source": ["# Linear Regression from Scratch\n", "Gradient descent on a toy dataset."]},
        {"cell_type": "code", "metadata": {}, "execution_count": 1, "outputs": [], "source": ["import numpy as np\n", "X = np.random.rand(100, 1)"]},
    ], "metadata": {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"}},
        "nbformat": 4, "nbformat_minor": 5}
    with open(p("Untitled.ipynb"), "w") as f:
        json.dump(nb, f, indent=1)


def screenshot():
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (800, 450), (250, 250, 250))
    ImageDraw.Draw(im).rectangle([40, 40, 760, 410], outline=(30, 30, 30), width=3)
    im.save(p("Screenshot 2026-10-30 142233.png"))


def mail():
    m = EmailMessage()
    m["From"] = "Prof. Anita Rao <anita.rao@vit.ac.in>"
    m["To"] = "ravi.kumar@example.com"
    m["Subject"] = "Re: Project review 2 schedule - BCSE306L"
    m["Date"] = "Tue, 27 Oct 2026 09:14:03 +0530"
    m["Message-ID"] = "<abc123@vit.ac.in>"
    m.set_content("Hi Ravi,\n\nYour project review 2 is on 4 November at 10 am in SJT 512.\n\nRegards\nAnita Rao")
    with open(p("mail.eml"), "wb") as f:
        f.write(bytes(m))


def zip_bomb():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", b"0" * (60 * 1024 * 1024))
    with open(p("bomb.docx"), "wb") as f:
        f.write(buf.getvalue())


if __name__ == "__main__":
    for fn in (paper, assignment, exam, certificate, receipt, ticket, slides, lab, resume, code, notebook,
               screenshot, mail, zip_bomb):
        fn()
    with open(p("sources.csv"), "w") as f:
        f.write("name,short_name,aliases,domains\n"
                "Vellore Institute of Technology,VIT,VIT University,vit.ac.in;vitstudent.ac.in\n"
                "Coursera Inc,Coursera,,coursera.org\n")
    print("samples written to", os.path.abspath(OUT))
