import hashlib
from pathlib import Path

DISTRACTORS = {
    "hostel_regulations.txt": """APEX UNIVERSITY RESIDENTIAL SERVICES MANUAL (POLICY HST-901)
Section 1. Curfew and Biometric Verification
1.1 All undergraduate hostel residents must return to their respective halls by 22:00 hours on weekdays and 22:30 hours on declared institutional holidays. Entry doors are automatically locked via electromagnetic access terminals.
1.2 Late entry between 22:01 and 23:00 hours requires biometric re-verification at the Central Security Gate-2 and incurs a non-negotiable incident surcharge of Rs 350 debited to the student terminal account.
1.3 Third consecutive curfew violations within a single semester trigger an automatic appearance before the Hostel Disciplinary Council presided over by Chief Warden Dr. Sunil V. Raghavan in Hall Administration Suite 102.

Section 2. Room Inventory and Electrical Appliance Guidelines
2.1 Each room is furnished with a standard wooden cot, mattress, study desk, ergonomic chair, and double-door steel almirah. Damage to standard inventory will be assessed against the caution deposit of Rs 10,000 deposited at admission.
2.2 Prohibited electrical appliances include immersion water heaters, induction cooktops, high-wattage halogen lamps, and personal refrigerators exceeding 45 liters capacity. 
2.3 Authorized appliances are restricted to laptops, mobile phone chargers, and single electric kettles rated below 750 Watts registered via Form EL-82 with the Block Supervisor.
2.4 Possession of unauthorized high-wattage heating elements attracts an immediate fine of Rs 2,500 and permanent confiscation of the appliance until semester culmination.

Section 3. Guest Accommodation and Overnight Stays
3.1 Immediate family members (parents and legal guardians only) may be accommodated in the University Guest House for a maximum of 3 consecutive nights at a subsidized tariff of Rs 850 per night upon 72 hours prior written notice to the Provost Office.
3.2 Day-scholar visitors are prohibited from entering residential corridors beyond 18:30 hours. Unsanctioned overnight hosting of external guests results in a mandatory fine of Rs 5,000 and possible hostel expulsion for the host resident.
""",

    "transport_policy.txt": """METROPOLITAN UNIVERSITY COMMUTER AND TRANSIT REGULATIONS (CODE TRN-304)
Section 1. Bus Pass Issuance and Smart Card Validation
1.1 The Department of Campus Transit operates a dedicated fleet of 28 compressed natural gas (CNG) buses serving 14 designated commuter corridors across the metropolitan region.
1.2 Semester bus passes are issued exclusively to verified full-time students upon payment of the transit fee of Rs 14,200 per academic term. Smart transit cards must be tapped against the contactless reader upon boarding at the designated stop.
1.3 Replacement of a damaged, demagnetized, or misplaced bus card requires submission of Form TR-04 to Transport Supervisor Mr. B. K. Shanmugam in Depot Administration Office A-4 along with a reissue fee of Rs 500.

Section 2. Boarding Protocols and Route Schedule Adherence
2.1 Morning feeder services commence boarding at origin terminals at precisely 06:45 hours, ensuring university campus arrival no later than 08:20 hours. Drivers are strictly prohibited from awaiting late passengers beyond designated departure marks.
2.2 Evening return services depart from the Central Campus Bus Loop at 16:45 hours and 18:15 hours respectively. Passengers must occupy forward passenger seating according to their route manifest.
2.3 Standing is permitted up to a maximum safety ceiling of 12 passengers in the center aisle. Overcrowding beyond this limit mandates the immediate dispatch of an auxiliary relief vehicle.

Section 3. Green Zone Campus Transit and Electric Shuttles
3.1 Internal transit across the 180-acre pedagogical zone is restricted to zero-emission battery electric vehicles (ZEVs). Autonomous shuttle carts circulate on a continuous 8-minute headway between Central Plaza and the Technology Park.
3.2 Personal fossil-fuel vehicles are strictly barred from entering the inner perimeter beyond Checkpoint Delta between 08:00 and 17:30 hours on instructional days.
3.3 Unauthorized parking in the electric charging bay incurs a towing fee of Rs 1,800 plus an administrative holding charge of Rs 200 per hour.
""",

    "sports_complex_code.txt": """IMPERIAL CAMPUS ATHLETIC COMPLEX OPERATIONAL CHARTER (POL-SPT-22)
Section 1. Membership Registration and Facility Access Hours
1.1 The Sardar Vallabhbhai Patel Athletic Complex is accessible daily to university students, academic staff, and registered alumni holding a valid biometric recreation clearance.
1.2 The Olympic-standard 50-meter aquatic center operates morning sessions from 06:00 to 09:30 hours and evening sessions from 16:30 to 20:30 hours under direct lifeguard surveillance.
1.3 Access to the strength conditioning gym requires completion of a mandatory fitness orientation conducted by Head Coach Marcus Anthony, followed by an annual registration levy of Rs 1,200 for student fitness cards.

Section 2. Indoor Court Bookings and Equipment Rental
2.1 Badminton, squash, and indoor basketball courts may be reserved up to 48 hours in advance through the Campus Sports Portal. Individual booking slots are restricted to 45 minutes per participant.
2.2 Non-marking footwear is strictly required on all hardwood and synthetic parquet surfaces. Entry with black-soled or outdoor running shoes results in an on-the-spot fine of Rs 600 and a 14-day booking suspension.
2.3 Racket and equipment rentals are available at the Equipment Desk in Pavilion B upon surrender of student identity cards. Damaged tournament shuttlecocks or cracked squash frames must be reimbursed at standard replacement value.

Section 3. Inter-Departmental Tournaments and Medical Clearances
3.1 Athletes participating in the Annual Chancellor Trophy must submit a comprehensive medical fitness clearance certified by the University Medical Center (Form MED-SPORT-1) at least 10 days prior to tournament inauguration.
3.2 Misconduct, unsportsmanlike behavior, or umpire intimidation during sanctioned competitions incurs an immediate red-card suspension and referral to the Sports Ethics Committee chaired by Dean of Athletics Dr. Preeti Grewal.
""",

    "it_acceptable_use.txt": """INSTITUTIONAL INFORMATION TECHNOLOGY POLICY (DIRECTIVE IT-SEC-108)
Section 1. Network Authentication and Bandwidth Allocations
1.1 The Information Technology Services Division (ITSD) provides secure wireless local area network connectivity (SSID: 'CampusNet-Secure') across all academic, administrative, and residential facilities.
1.2 Every student is provisioned an individual network credential linked to their institutional identity number, granting a monthly fair-usage download quota of 120 Gigabytes at symmetric 100 Mbps throughput.
1.3 Bandwidth consumption exceeding the allocated quota results in automatic throttling to 2 Mbps until the first calendar day of the subsequent billing cycle unless an emergency quota extension is authorized via the ITSD Helpdesk.

Section 2. Hardware Registration and Security Compliance
2.1 Personal laptops, tablets, and mobile devices connecting to the campus intranet must register their network interface Media Access Control (MAC) address via the ITSD Self-Service Portal.
2.2 Devices running end-of-life operating systems or exhibiting unpatched critical vulnerabilities will be quarantined dynamically into an isolated VLAN until remediated.
2.3 The deployment of rogue wireless access points, unauthorized DHCP servers, packet sniffing utilities, or unlicensed network bridging devices in residential halls is strictly forbidden.

Section 3. Cybersecurity Violations and Sanctions
3.1 Engaging in network penetration testing, distributed denial of service (DDoS) simulations, password cracking, or automated credential stuffing without explicit written authorization from Chief Information Officer Dr. Tarun Sengupta constitutes a Class-A disciplinary violation.
3.2 Violators are subject to immediate termination of university network privileges, forfeiture of computer laboratory access for two consecutive semesters, and referral to the Cyber Crime Wing of the State Police Department.
""",

    "scholarship_guidelines.txt": """UNIVERSITY ENDOWMENT SCHOLARSHIP AND FINANCIAL AID STATUTE (SCH-2026)
Section 1. Merit-Cum-Means Scholarship Criteria
1.1 The Vice-Chancellor Merit-Cum-Means Endowment awards 150 annual tuition remissions to meritorious undergraduate students whose annual family gross income does not exceed Rs 6,50,000 from all legitimate sources.
1.2 Applicants must demonstrate an unblemished academic track record, retaining a minimum Cumulative Grade Point Average (CGPA) of 8.25 across all completed coursework without any standing backlog or disciplinary warnings.
1.3 Beneficiaries receive a 75% remission of tuition fees alongside a living stipend allowance of Rs 4,500 per month credited directly to their registered National Automated Clearing House (NACH) bank accounts.

Section 2. Application Windows and Verification Documentation
2.1 The scholarship application portal opens annually on August 15 and closes definitively on September 30 at 17:00 hours. Belated submissions are dismissed without review.
2.2 Required documentary exhibits include: certified Income Certificate issued by a Revenue Officer not below the rank of Tehsildar, certified copies of semester mark sheets, and an affidavit of non-receipt of concurrent central or state financial aid.
2.3 All applicant claims are audited by the Financial Aid Screening Committee convened by Registrar Dr. Meera Nambiar in Senate Chamber Room 204.

Section 3. De-registration and Clawback Provisions
3.1 If a recipient falls below the 8.25 CGPA maintenance floor or engages in academic malpractice during the award tenure, the scholarship is discontinued with immediate effect.
3.2 In the event that an applicant secures funding through fraudulent income representations, the University initiates formal recovery proceedings to recoup all disbursed sums with an accrued compound interest rate of 12% per annum.
""",

    "placement_cell_charter.txt": """CAREER DEVELOPMENT AND CORPORATE ENGAGEMENT MANUAL (POL-CDC-405)
Section 1. Student Placement Registration and Eligibility
1.1 The Corporate Development Centre (CDC) coordinates on-campus recruitment drives, internships, and corporate industrial apprenticeships for graduating undergraduate and postgraduate cohorts.
1.2 Eligibility requires registration with the CDC portal during the mandatory sign-up window between June 1 and July 15, along with payment of a non-refundable professional placement development levy of Rs 3,000.
1.3 Students must possess an active aggregate percentage of 60% or a CGPA of 6.50 with a maximum of one active backlog permitted at the time of recruitment commencement.

Section 2. One-Student One-Offer Policy and Dream Tier Exceptions
2.1 The University enforces a strict 'One-Student One-Offer' paradigm. Once an offer of employment is tendered by a recruiting company, the student is disqualified from participating in subsequent placement proceedings.
2.2 An exception is granted for 'Dream Category' corporate entities offering an annual cost-to-company (CTC) package exceeding Rs 14,00,000 per annum, provided the initial placement offer was below Rs 7,00,000 per annum.
2.3 Participation in a Dream Category drive requires prior written endorsement from Placement Director Prof. Alok Shrivastava.

Section 3. Interview Ethics, Attendance, and Penalty Surcharges
3.1 Students shortlisted for corporate interviews who fail to attend without a verifiable medical emergency approved 24 hours prior are levied a penalty of Rs 2,500 and debarred from the subsequent three corporate recruitment drives.
3.2 Fabrication of resume accomplishments, falsified grade transcripts, or counterfeit project credentials results in immediate revocation of CDC registration and formal communication of debarment to all prospective corporate recruitment partners.
""",

    "anti_ragging_code.txt": """INSTITUTIONAL ZERO-TOLERANCE CODE AGAINST HARASSMENT (REG-ANTI-007)
Section 1. Definition and Statutory Jurisdiction
1.1 In strict compliance with directives from the Supreme Court of India and University Grants Commission statutory regulations, the University enforces an unconditional zero-tolerance policy regarding ragging in all manifestations.
1.2 Ragging encompasses any spoken or written conduct, rowdy behavior, tease, humiliation, physical abuse, or psychological intimidation causing apprehension, distress, or involuntary financial extortion of junior scholars.
1.3 The jurisdiction of this statute extends to academic premises, university transit, affiliated hostels, sports grounds, and cyber communications between registered scholars.

Section 2. Institutional Squads and Emergency Reporting Terminals
2.1 The University Anti-Ragging Committee is chaired directly by the Vice-Chancellor, while the Anti-Ragging Flying Squad operates under the supervision of Chief Proctor Dr. Arvind Swaminathan.
2.2 Dedicated emergency SOS callboxes are positioned at 12 outdoor campus locations, offering direct two-way audio connectivity to the Campus Security Command Center.
2.3 Reports may be submitted anonymously 24/7 via the toll-free emergency helpline 1800-425-9911 or through the secure portal 'antiragging.apex.edu'.

Section 3. Inquest Procedures and Statutory Sanctions
3.1 Upon receipt of a grievance, the Flying Squad initiates a preliminary inquiry within 24 hours and delivers its formal findings to the Proctorial Board within 72 hours.
3.2 Confirmed infractions mandate the immediate enforcement of statutory punishments, including: suspension from classes and residential halls for up to two academic semesters, withholding of scholarships and examination results, debarment from institutional representation, or permanent expulsion.
3.3 In cases involving severe assault, physical coercion, or psychological trauma, the Proctorial Board files a formal First Information Report (FIR) with the local jurisdictional police precinct within 12 hours of inquiry conclusion.
""",

    "cafeteria_hygiene_policy.txt": """FOOD SAFETY, NUTRITION, AND CATERING STANDARDS CHARTER (POL-CAF-55)
Section 1. Commercial Licensing and Hygiene Certifications
1.1 All commercial food and beverage establishments operating on campus, including the Central Food Court, North Lawn Kiosk, and residential mess facilities, must possess an active license issued by the Food Safety and Standards Authority of India (FSSAI).
1.2 Food handling personnel are obligated to undergo quarterly certified medical health evaluations, including skin condition assessments, tuberculosis screenings, and enteric pathogen tests certified by the University Health Officer.
1.3 Hair nets, disposable protective gloves, and sanitized kitchen aprons are mandatory within culinary preparation areas. Non-compliance attracts an immediate inspection fine of Rs 1,500 per detected infraction.

Section 2. Periodic Quality Audits and Water Testing Protocols
2.1 The Campus Food Safety and Quality Assurance Committee conducts unannounced bi-weekly inspections evaluating culinary hygiene, food storage temperatures, and preparation cleanliness.
2.2 Drinking water dispensers and reverse osmosis (RO) filtration units undergo microbiological pathogen testing on the 5th business day of each month by an independent accredited laboratory.
2.3 Any commercial vendor whose food sample fails microbial safety standards is ordered to suspend operations immediately and levied a restorative penalty of Rs 25,000 for the first violation.

Section 3. Sustainable Waste Management and Pricing Governance
3.1 Single-use non-biodegradable plastics, including styrofoam cups, thin polythene carry bags, and plastic straws, are strictly prohibited across all university dining zones.
3.2 Organic wet waste must be segregated into color-coded green collection bins for transport to the campus anaerobic biogas digester by 21:00 hours daily.
3.3 Menu item tariffs are fixed by the University Cafeteria Pricing Board chaired by Finance Officer Mr. K. Ramanujam; unapproved price escalations result in contract termination.
""",

    "laboratory_safety_manual.txt": """CENTRAL SCIENTIFIC INSTRUMENTATION AND LAB SAFETY MANUAL (LAB-SAF-14)
Section 1. Laboratory Access and Personal Protective Equipment (PPE)
1.1 Access to all specialized teaching and research laboratories, including Chemistry, Biotechnology, and Materials Science, is restricted to authorized scholars possessing active RFID laboratory clearances.
1.2 Standard mandatory PPE comprises a full-sleeved 100% cotton laboratory coat, splash-resistant chemical goggles conforming to ANSI Z87.1 standards, and closed-toe leather footwear.
1.3 Entry into chemical synthesis facilities wearing open sandals, synthetic nylon garments, or shorts is strictly forbidden and results in immediate laboratory eviction.

Section 2. Chemical Storage, Hazard Communication, and Hazardous Waste
2.1 All chemical receptacles must bear standard Globally Harmonized System (GHS) warning pictograms, lot identifiers, and preparation dates. Unlabeled chemical beakers will be neutralized and discarded.
2.2 Flammable organic solvents exceeding 5 liters in volume must be stored inside dedicated fire-rated steel safety cabinets fitted with mechanical ventilation.
2.3 Chemical waste streams must be segregated into designated color-coded containers: Red (halogenated solvents), Yellow (heavy metal solutions), and Blue (aqueous non-toxic solutions).
2.4 Pouring organic solvents or concentrated acids into municipal drainage sinks incurs a mandatory laboratory suspension of 30 days and an environmental remediation fine of Rs 8,000.

Section 3. Emergency Evacuation and Spill Containment Protocols
3.1 Every laboratory facility is equipped with an emergency overhead drench shower and eyewash station tested on a weekly basis by Laboratory Technician Mr. V. Satish.
3.2 In the event of a hazardous material spill exceeding 500 milliliters, students must immediately pull the laboratory alarm lever, evacuate the premises via Fire Exit Corridor 3, and notify the Hazardous Materials Response Unit.
""",

    "student_council_bylaws.txt": """STUDENT SENATE AND REPRESENTATIVE COUNCIL CONSTITUTION (GOV-STU-02)
Section 1. Composition and Representative Mandate
1.1 The Student Senate constitutes the official representative deliberative body of the student community, advocating student welfare, academic feedback, and co-curricular development before University Authorities.
1.2 The Senate consists of 24 elected Departmental Representatives, 6 Nominated Cultural and Sports Secretaries, and 4 Executive Officers: President, Vice-President, General Secretary, and Treasurer.
1.3 Executive Officers must be registered full-time students in their penultimate year of study, possessing a minimum CGPA of 7.50 without any pending academic backlogs or disciplinary sanctions.

Section 2. Election Governance and Campaign Ethics
2.1 General elections for the Student Senate are organized annually during the third week of September under the autonomous authority of the University Election Commission headed by Prof. Geeta Krishnan.
2.2 The maximum permissible campaign expenditure per candidate is capped at Rs 5,000, substantiated by original tax invoices submitted to the Commission within 48 hours of election culmination.
2.3 Printed posters, loudspeakers, off-campus political endorsements, and defamatory digital campaigns on social media are prohibited. Violations result in instantaneous candidate disqualification.

Section 3. Senate Deliberations, Quorum, and Financial Auditing
3.1 Regular parliamentary sessions of the Student Senate convene on the first Saturday of each month during the academic semester in the Old Senate Hall.
3.2 A quorum of two-thirds of the total voting membership is required to pass substantive policy resolutions or allocate student activity funds.
3.3 The annual activity budget of the Student Senate (Rs 18,50,000) is subjected to an exhaustive internal audit by the University Comptroller Office prior to the commencement of the subsequent fiscal cycle.
""",

    "internship_credit_framework.txt": """ACADEMIC INTERNSHIP AND PRACTICUM ACCREDITATION GUIDELINES (ACAD-INT-33)
Section 1. Mandatory Internship Timelines and Credit Weights
1.1 All candidates enrolled in four-year Bachelor of Technology degree programs must satisfactorily complete an industrial or research internship lasting not less than 8 consecutive weeks.
1.2 The internship must be undertaken between the conclusion of the sixth semester and the commencement of the seventh semester, carrying 4 academic credits toward degree completion.
1.3 Internships pursued with non-registered startup companies or unverified training institutes will not be accredited unless approved by Departmental Faculty Coordinator Dr. Ramesh Chandra.

Section 2. Progress Monitoring and Industry Mentor Evaluation
2.1 Interns must submit a bi-weekly progress memorandum summarizing project assignments, tools utilized, and milestones achieved through the university academic ERP portal.
2.2 At the conclusion of the internship term, the corporate industry mentor must submit a confidential evaluation appraisal (Form INT-APP-4) assessing technical proficiency, professionalism, and attendance directly to the Dean of Academics.
2.3 A minimum rating of 'Satisfactory' (Grade B or equivalent) from the corporate supervisor is required to qualify for academic credit defense.

Section 3. Comprehensive Viva-Voce and Final Defense
3.1 Interns must submit a hardbound technical practicum report of 40 to 60 pages formatted according to university thesis guidelines within 14 days of academic resumption.
3.2 Candidates defend their project findings before a three-member Departmental Evaluation Committee during the scheduled viva-voce examination in mid-August.
3.3 Failure to appear for the defense or submission of a plagiarized report results in an 'Incomplete' (I) grade, obligating the candidate to repeat the internship requirement during the following summer vacation.
""",

    "research_ethics_code.txt": """SCHOLARLY INTEGRITY AND RESEARCH CONDUCT CODE (ETH-RES-77)
Section 1. Ethical Governance and Institutional Review Board (IRB)
1.1 All scholarly research investigations involving human participants, patient clinical datasets, biological specimens, or animal models must obtain prior clearance from the Institutional Ethics Committee (IEC).
1.2 Protocols must be submitted to IRB Member Secretary Dr. Ananya Mukherjee at least 30 days prior to participant recruitment, accompanied by certified informed consent documentation.
1.3 Conducting biomedical or behavioral research without formal IRB approval leads to immediate thesis invalidation and cancellation of doctoral fellowships.

Section 2. Authorship Standards and Plagiarism Thresholds
2.1 Co-authorship on scholarly manuscripts and conference proceedings must be restricted to individuals who have made substantial, demonstrable intellectual contributions to experimental design, data acquisition, or analysis.
2.2 The University enforces an uncompromised anti-plagiarism standard. All research dissertations and journal submissions must undergo automated similarity screening utilizing Turnitin.
2.3 The maximum acceptable text similarity index is set at 10%, strictly excluding cited references, standard mathematical formulas, and generic methodological nomenclature.
2.4 Similarity indexes exceeding 25% are classified as Level-3 Academic Malpractice, resulting in immediate expulsion of the research scholar and a 3-year research supervision debarment for the faculty guide.

Section 3. Data Archiving, Intellectual Property, and Conflict of Interest
3.1 Original raw experimental datasets, spectroscopic logs, and computational source scripts must be deposited in the secure University Research Data Repository (ApexData-Archive) for a minimum retention window of 7 years.
3.2 Any potential commercial patent, invention, or revenue-generating software utility developed using university laboratory resources is governed by the 60:40 Institutional Intellectual Property Sharing Scheme.
""",

    "grading_curving_policy.txt": """ACADEMIC PERFORMANCE ASSESSMENT AND GRADE MODERATION STATUTE (POL-GRD-12)
Section 1. Absolute Versus Relative Grading Paradigms
1.1 Courses with an active enrollment exceeding 40 students employ a Relative Grading System based on standard deviations calculated from the class mean mark distribution.
1.2 Courses with enrollments of 40 or fewer candidates are evaluated under the Absolute Grading Scheme, where grades are allocated as: O (90-100%), A+ (80-89%), A (70-79%), B+ (60-69%), B (50-59%), C (42-49%), and F (Below 42%).
1.3 In relative grading, the median passing boundary for Grade C is positioned at $(\mu - 1.5\sigma)$, where $\mu$ denotes the class arithmetic mean and $\sigma$ denotes the sample standard deviation.

Section 2. Continuous Internal Evaluation (CIE) Weights
2.1 The overall semester evaluation is bifurcated into Continuous Internal Evaluation (CIE) carrying 40% total weight and the End-Semester Examination (ESE) carrying 60% total weight.
2.2 CIE components comprise: two centralized mid-term written quizzes (15% each), unannounced pedagogical classroom tutorials (5%), and assigned homework term papers (5%).
2.3 Students must attain a minimum qualifying threshold of 40% in aggregate CIE scores to be issued an examination hall ticket for the end-semester written session.

Section 3. Grade Moderation Committee and Incomplete Grades
3.1 Grade distributions submitted by course instructors undergo formal review by the Departmental Grade Moderation Committee chaired by Department Head Prof. S. N. Roy.
3.2 Moderation adjustments exceeding 4 raw marks require explicit written sanction from the Controller of Examinations.
3.3 A temporary 'Incomplete' (I) grade awarded due to verified medical hospitalization must be formally cleared by sitting a special makeup assessment within 45 days of semester commencement.
""",

    "alumni_association_charter.txt": """ALUMNI RELATIONS AND INSTITUTIONAL ADVANCEMENT CHARTER (ALUM-DIR-88)
Section 1. Membership Governance and Chapter Affiliation
1.1 Every graduate receiving an academic degree or diploma from the University is automatically inducted as an Ordinary Member of the Apex University Global Alumni Association (AUGAA).
1.2 Life membership requires an endowment contribution of Rs 5,000 paid at the time of final convocation, which supports the Alumni Student Support Bursary Fund.
1.3 Regional alumni chapters may be established in any metropolitan area hosting 50 or more registered alumni upon submitting an application to Alumni Relations Director Mrs. Deepa Chawla in Founders Hall.

Section 2. Annual Alumni Convention and Homecoming Timetable
2.1 The Grand Annual Alumni Homecoming Convention is hosted annually on campus during the second weekend of December.
2.2 Milestone reunion celebrations are commemorated for the Silver Jubilee (25 years) and Golden Jubilee (50 years) graduating classes, with commemorative citations presented by the Chancellor.
2.3 The Distinguished Alumnus Award (DAA) nominations open on July 1 and close on August 31, recognizing singular excellence in Corporate Leadership, Public Service, Academic Research, or Entrepreneurship.

Section 3. Financial Stewardship and Endowment Allocations
3.1 Philanthropic contributions and endowment funds donated by alumni are managed under the fiduciary oversight of the University Trust Board.
3.2 Donors contributing sums exceeding Rs 25,00,000 are honored with naming privileges for pedagogical lecture halls, laboratory benches, or seminar spaces for a stipulated period of 15 years.
3.3 All financial transactions and fund disbursements are audited annually by an external firm of Chartered Accountants, with the verified balance sheet published on the alumni relations portal.
""",

    "health_center_protocol.txt": """UNIVERSITY HEALTH SERVICES AND EMERGENCY MEDICAL PROTOCOL (UHS-MED-09)
Section 1. Health Center Operations and Clinical Staffing
1.1 The Dr. B. C. Roy Memorial University Health Center operates 24 hours daily, 365 days a year, providing primary outpatient healthcare, emergency resuscitation, and temporary medical observation.
1.2 Clinical consultations are conducted by resident medical officers, supported by visiting medical specialists in orthopedics, ophthalmology, dermatology, and psychiatry.
1.3 Consultations, routine prescription pharmaceutical supplies, and basic diagnostic blood investigations are provided free of charge to all registered students presenting a valid university smart identity card.

Section 2. Inpatient Admissions and Critical Emergency Transfers
2.1 The health center maintains an 8-bed short-stay inpatient infirmary for patients requiring intravenous rehydration, vital sign monitoring, or febrile observation.
2.2 Inpatient admissions exceeding 48 hours duration mandate patient transfer to the affiliated 800-bed Tertiary University Teaching Hospital.
2.3 The emergency medical response fleet comprises two fully equipped Advance Life Support (ALS) ambulances stationed outside Health Center Bay 1. Emergency transit requests are routed via Campus Dial-Ext 333.

Section 3. Mental Health Counseling and Confidentiality
2.1 The Center for Psychological Wellness operates within the Health Center building, offering free, confidential psychological therapy, stress reduction counseling, and crisis intervention services.
2.2 The counseling staff comprises three licensed clinical psychologists headed by Chief Counselor Dr. Farida Khan.
2.3 Counseling interactions and diagnostic notes are protected under strict medical doctor-patient confidentiality, exempt from inclusion in student academic transcripts or placement files except in cases of immediate self-harm threat.
""",
}

def main():
    target_dir = Path("eval/data/distractors")
    target_dir.mkdir(parents=True, exist_ok=True)
    
    sha_lines = []
    for filename, content in sorted(DISTRACTORS.items()):
        filepath = target_dir / filename
        # Ensure consistent UTF-8 text with standard newlines
        clean_content = content.strip() + "\n"
        filepath.write_text(clean_content, encoding="utf-8")
        
        char_count = len(clean_content)
        file_hash = hashlib.sha256(clean_content.encode("utf-8")).hexdigest()
        sha_lines.append(f"{file_hash}  {filename}")
        print(f"Created {filename}: {char_count} chars, SHA-256: {file_hash[:12]}...")
        assert 1400 <= char_count <= 2600, f"{filename} character count {char_count} outside 1.4k-2.6k range!"

    manifest_path = target_dir / "DISTRACTORS.sha256"
    manifest_path.write_text("\n".join(sha_lines) + "\n", encoding="utf-8")
    print(f"\nWritten {len(DISTRACTORS)} distractor documents to {target_dir}")
    print(f"Written manifest to {manifest_path}")

if __name__ == "__main__":
    main()
