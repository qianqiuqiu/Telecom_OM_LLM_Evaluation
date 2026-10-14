# 人工复核清单（含原文，不入库）

逐题看核查证据，在“你的结论”处填 correct / wrong / ambiguous。

## question 37 · needs_review · Standards overview

Which NGAP procedure is used for inter-system load balancing? [3GPP Release 17]

1. eNB Configuration Transfer
2. Downlink RAN Configuration Transfer
3. Uplink RAN Configuration Transfer  ← 标准答案
4. MME Configuration Transfer

盲答：Qwen 4，Claude 3

- inv1：**ambiguous** — Options 1 and 4 are S1AP procedures, not NGAP. NGAP carries inter-system SON and load-balancing information in both directions: the NG-RAN node sends it in Uplink RAN Configuration Transfer and receives it in Downlink RAN Configuration Transfer. That makes both option 2 and option 3 defensible. The marked option 3 is plausible because the NG-RAN node starts the exchange, but it is not the only right answer.（来源：own knowledge (3GPP TS 38.413 Rel-17 clause 8.16; TS 38.300 inter-system load balancing)）
- inv2：**correct**（应为 3） — Options 1 and 4 are S1AP procedures, not NGAP. In NGAP (TS 38.413), the NG-RAN node starts inter-system SON/load-balancing information exchange, such as the inter-system resource status request/report toward E-UTRAN, with the Uplink RAN Configuration Transfer procedure. The AMF then delivers it with Downlink RAN Configuration Transfer. The uplink procedure is the initiating one and the best answer, but the downlink procedure is also involved, so there is slight ambiguity.（来源：own knowledge (3GPP TS 38.413 Rel-17, Uplink/Downlink RAN Configuration Transfer; TS 38.300 inter-system load balancing)）

你的结论：

## question 135 · needs_review · Standards specifications

What does a UE determine when selecting a power for an S-SS/PSBCH block transmission occasion? [3GPP Release 17]

1. Value of dl-P0-PSBCH-r16
2. Value of dl-Alpha-PSBCH
3. Number of resource blocks for a S-SS/PSBCH block transmission
4. Value of dl-P0-PSBCH-r17
5. Value of dl-P0-PSBCH-r16 if provided, else dl-Alpha-PSBCH  ← 标准答案

盲答：Qwen 3，Claude 5

- inv1：**ambiguous** — In TS 38.213 clause 16, the S-SS/PSBCH power is min(PCMAX, PO,S-SSB + 10log10(2^mu*11) + alpha*PL). PO is dl-P0-PSBCH-r16 (or -r17) and alpha is dl-Alpha-PSBCH, both used together when PO is provided. Otherwise the power is PCMAX. Option 5's 'r16 if provided, else dl-Alpha-PSBCH' misstates this fallback. The UE also determines several of the listed quantities, so the question is flawed.（来源：own knowledge (3GPP TS 38.213 Rel-16/17, sidelink S-SS/PSBCH power control); web search unavailable）
- inv2：**ambiguous** — TS 38.213 clause 16.1 says: if dl-P0-PSBCH-r16 is provided, P = min(PCMAX, P0 + 10log10(2^mu*M_RB) + alpha*PL), where alpha is dl-Alpha-PSBCH (or 1 if not provided); otherwise P = PCMAX. Option 5 ('else dl-Alpha-PSBCH') misstates the fallback, which is PCMAX. Option 3 (number of RBs, M_RB) is also an input to the formula. No option is cleanly correct.（来源：own knowledge (3GPP TS 38.213 clause 16.1, sidelink S-SS/PSBCH power control); web search unavailable）

你的结论：

## question 177 · needs_review · Standards overview

How does packet duplication potentially reduce jitter?

1. By providing frequency and path diversity
2. By avoiding retransmissions
3. By minimizing variance in latency  ← 标准答案
4. By improving handover performance
5. By improving throughput during TCP slow start phase

盲答：Qwen 1，Claude 2

- inv1：**ambiguous** — Duplication lowers jitter mainly because retransmissions are avoided: the first copy to arrive is used, which cuts latency spikes. Option 2 gives that mechanism. Option 3 ('minimizing variance in latency') is close to the definition of reduced jitter. Option 1 (diversity) is the underlying cause of the reliability gain. More than one option is defensible.（来源：own knowledge (3GPP URLLC / PDCP duplication literature)）
- inv2：**ambiguous** — Duplication sends the same packet over independent paths or carriers (diversity), which avoids retransmissions and so reduces latency variance. Option 3 describes the effect, and options 1 and 2 describe the mechanism. The question asks 'how', so options 1 and 2 are as defensible as the marked option 3.（来源：own knowledge (PDCP duplication, 3GPP URLLC studies)）

你的结论：

## question 636 · needs_review · Standards specifications

How does the NWDAF collect information from the UPF? [3GPP Release 18]

1. Via NEF(PFDF)
2. Via NRF
3. Via SMF  ← 标准答案
4. Directly from UPF

盲答：Qwen 3，Claude 4

- inv1：**ambiguous** — Release 16 NWDAF collected UPF data through the SMF. Release 17/18 added UPF event exposure (Nupf_EventExposure), so in TS 23.288 / TS 23.502 the NWDAF can collect UPF data directly or through the SMF. With a Release 18 tag, both option 3 (via SMF, the marked one) and option 4 (directly from UPF) are defensible.（来源：own knowledge (3GPP TS 23.288 clause 6.2.2, TS 23.502 clause 4.15.4.5)）
- inv2：**ambiguous** — In Rel-17/18 TS 23.288, the NWDAF can collect UPF data either via the SMF (SMF-mediated UPF event exposure) or directly from the UPF (Nupf_EventExposure subscription). Both options 3 and 4 are defensible.（来源：own knowledge (3GPP TS 23.288 Rel-18 clause 6.2.2 data collection; TS 23.502 UPF event exposure)）

你的结论：

## question 717 · needs_review · Standards specifications

What happens when the Control Plane data back-off timer is running? [3GPP Release 18]

1. The UE cannot initiate any data transfer via Control Plane CIoT 5GS Optimization  ← 标准答案
2. The AMF stops processing any further requests (except for exception reporting and paging response) for data transport via Control Plane Service Request from that UE
3. The UE is allowed to initiate Service Request procedures for activating User Plane connection
4. The UE is allowed to initiate Session Management procedures for emergency services

盲答：Qwen 2，Claude 2

- inv1：**ambiguous** — TS 23.501 cl. 5.19.7.6 says both things. The UE shall not start any data transfer via Control Plane CIoT 5GS Optimisation, with exceptions for exception reporting and paging responses; that is option 1. The AMF stores the timer per UE and does not process further Control Plane Service Requests for data transport, with the same exceptions; that is option 2, almost word for word. The notes also say the timer does not affect other MM/SM procedures or user-plane data, which partly supports options 3 and 4. Option 2 is the closest match to the spec text, and option 1 leaves out the exceptions. More than one option is defensible, so the marked answer (option 1) is not uniquely right.（来源：3GPP TS 23.501 cl. 5.19.7.6 (https://www.itecspec.com/3gpp/23.501/s/5.19.7.6)）
- inv2：**ambiguous** — The rule for the CP data back-off timer (TS 23.501 CIoT clauses, mirroring TS 23.401 4.7.7) is that, while the timer runs, the UE shall not initiate data transfer via Control Plane CIoT optimisation, except for exception reporting and responses to paging. The AMF stores the timer and rejects further CP data-transport requests from that UE, with the same exceptions. Option 1 paraphrases the UE-side rule but leaves out the exceptions. Option 2 paraphrases the network-side rule and does include them. The spec also lets the UE use User Plane Service Requests (option 3) and emergency procedures (option 4) while the timer runs. Several options are defensible, so option 1 is not uniquely right.（来源：own knowledge (3GPP TS 23.501 Rel-18 CIoT CP data back-off; TS 23.401 4.7.7)）

你的结论：

## question 759 · needs_review · Standards overview

What is the role of the Near Real-Time RAN Intelligent Controller (Near-RT RIC)?

1. To control the O-DUs through the E2 interface
2. To serve as the user categorization module
3. To compute the MAP vector for each O-RU
4. All of the above  ← 标准答案
5. None of the above

盲答：Qwen 1，Claude 1

- inv1：**ambiguous** — Under O-RAN, the Near-RT RIC controls E2 nodes (O-CU/O-DU) over the E2 interface, so option 1 holds in general. Options 2 and 3 (a user categorization module, a MAP vector per O-RU) only make sense in one particular research paper's design, and the question gives no context for them. The marked option 4, 'All of the above', depends on that missing context; from the standard alone, option 1 is the defensible answer.（来源：own knowledge (O-RAN.WG1 Architecture Description; O-RAN.WG3 E2 specs)）
- inv2：**ambiguous** — The standard role of the Near-RT RIC is to control E2 nodes (O-CU/O-DU) over the E2 interface, which is option 1. Options 2 and 3 (user categorization, MAP vector per O-RU) describe xApp functions from a specific paper, not the Near-RT RIC in general. 'All of the above' may match the source paper, but on general knowledge option 1 is the defensible answer, so neither option is uniquely right.（来源：O-RAN.WG1 architecture description; own knowledge）

你的结论：

## question 1143 · needs_review · Standards specifications

What is the key characteristic of a roaming broker enabled Home Environment? [3GPP Release 18]

1. It has a direct commercial agreement with different serving networks.
2. It interworks with one or more serving network operators.
3. It uses fraud and cost control mechanisms to ensure charges do not exceed credit limits.
4. It routes registration requests to its serving networks.
5. It is capable of operating as a roaming broker.  ← 标准答案

盲答：Qwen 未跑，Claude 2

- inv1：**ambiguous** — Neither 3GPP TS 22.101 nor TS 21.905 seems to define 'roaming broker enabled Home Environment'. The phrase appears only in TS 22.115 clause 8 (Automatic Roaming Agreements), in a note saying such an HE should interoperate with an R99 serving network. That clause also says each Home Environment should interwork with one or more serving network operators (option 2, but this applies to every HE), that any serving network shall be capable of operating as a roaming broker (close to option 5, but it is said of serving networks, not the HE), and it covers fraud and cost control (option 3). The question was built from this clause and has no single defensible answer. Option 5 just restates the term, and option 2 is also defensible.（来源：3GPP TS 22.115 clause 8 (https://itecspec.com/3gpp/22.115/s/8); TS 22.101 clause 3.1 checked, no definition found）
- inv2：**ambiguous** — TS 22.115 clause 8 never defines 'roaming broker enabled Home Environment'. The term appears only in a note saying such an HE should interoperate with a R99 Serving Network. The phrase in option 5, 'capable of operating as a roaming broker', is said about serving networks ('any serving network shall be capable of operating as a roaming broker'), not about the HE. Option 2 (interworks with serving network operators, via a broker) is just as defensible. The question is flawed.（来源：3GPP TS 22.115 clause 8 (https://itecspec.com/3gpp/22.115/s/8)）

你的结论：

## question 1274 · needs_review · Standards specifications

What is the SNR target for higher CBWs assuming 16 and 20 dB? [3GPP Release 18]

1. 14.4 dB
2. 18.6 dB
3. 16 dB  ← 标准答案
4. 20 dB

盲答：Qwen 未跑，Claude 2

- inv1：**ambiguous** — The question gives two SNR assumptions in its own wording ("assuming 16 and 20 dB") and offers both 16 dB (opt 3) and 20 dB (opt 4) as answers. No single option can be picked out from the wording, and the Rel-18 TR context it comes from is not stated. The question is malformed.（来源：own knowledge）
- inv2：**ambiguous** — The question names the assumed SNRs (16 and 20 dB), and options 3 and 4 are exactly those two values. Options 1 and 2 (14.4 and 18.6 dB) look like derived targets. With two assumed values in the stem and a single-answer format, no one option is uniquely right. I could not find the source Rel-18 text to confirm which value the passage means.（来源：own knowledge (no source located)）

你的结论：

## question 1321 · needs_review · Standards specifications

What is the purpose of the N26 interface in the non-roaming architecture for interworking between 5GS and EPC? [3GPP Release 18]

1. To enable interworking between EPC and the NG core  ← 标准答案
2. To support subset of the functionalities that are supported over S10
3. To provide inter-CN interface between the MME and 5GS AMF
4. To support interworking between EPC and NG-RAN

盲答：Qwen 3，Claude 3

- inv1：**ambiguous**（应为 1） — TS 23.501 clause 4.3.1 says: 'N26 interface is an inter-CN interface between the MME and 5GS AMF in order to enable interworking between EPC and the NG core... N26 supports subset of the functionalities (essential for interworking) that are supported over S10.' Options 1, 2 and 3 each come almost word for word from this passage, so all three are defensible. Option 1 states the purpose most directly, but the marked answer is not uniquely right.（来源：3GPP TS 23.501 Rel-18 clause 4.3.1 (own knowledge of text)）
- inv2：**correct**（应为 1） — TS 23.501 clause 4.3.1 says N26 is an inter-CN interface between the MME and 5GS AMF 'in order to enable interworking between EPC and the NG core'. Option 3 is that description and option 2 (subset of S10 functions) is also stated there. The question asks for the purpose, which is the 'in order to' clause, so option 1 is the best answer, though options 2 and 3 are true statements.（来源：own knowledge (3GPP TS 23.501 clause 4.3.1)）

你的结论：

## question 1374 · needs_review · Standards overview

What is the function of the window mechanism in TCP? [TCP/IP]

1. To reserve buffer space
2. To guarantee complete reliability
3. To acknowledge the receipt of data
4. To set up a connection
5. To organize the data stream  ← 标准答案

盲答：Qwen 1，Claude 1

- inv1：**ambiguous** — The TCP sliding window is used for flow control. It limits how much unacknowledged data can be outstanding, based on the receiver's buffer space. None of the options states this cleanly. 'Organize the data stream' (marked 5) is vague. 'Reserve buffer space' (1) is also arguable, since the advertised window reflects the receiver's buffer. The question is poorly worded and no single option is clearly best.（来源：own knowledge (RFC 793 flow control / window semantics)）
- inv2：**ambiguous** — TCP's sliding window does flow control: the receiver advertises how many octets it can still buffer (RFC 793). None of the options says 'flow control'. 'Organize the data stream' (marked option 5) is vague, and 'reserve buffer space' (option 1) is at least as defensible, because the window reflects receiver buffer space. No single option is clearly right.（来源：own knowledge (RFC 793 window semantics)）

你的结论：

## question 1505 · needs_review · Standards overview

Which country has a maximum transmission power of 30 dBm in the frequency range of 5725-5850 MHz?

1. China
2. United States
3. Canada
4. Brazil
5. Europe  ← 标准答案

盲答：Qwen 4，Claude 2

- inv1：**wrong**（应为 2） — The US FCC U-NII-3 band (5725-5850 MHz) allows 1 W of conducted power, which is 30 dBm; this is the standard 30 dBm figure. Europe (ETSI) does not allow 30 dBm in this band: SRD use there is about 25 mW (14 dBm), and BFWA uses a different EIRP limit. So the marked option 5 (Europe) is wrong. Canada and Brazil follow US-like rules, so option 2 is not perfectly unique, but it is the best answer.（来源：own knowledge (FCC 47 CFR 15.407; ETSI EN 300 440 / EN 302 502)）
- inv2：**ambiguous** — At 5725-5850 MHz the US (FCC 15.247/15.407) allows 1 W (30 dBm) conducted output. Canada (RSS-247) and Brazil (Anatel) set the same 1 W limit, and China allows about 33 dBm EIRP. Europe does not generally allow 30 dBm in this band (SRD at 25 mW, or BFWA under EN 302 502 at a higher EIRP). So several options are defensible, and the marked 'Europe' is doubtful. The answer depends on an unknown source table.（来源：own knowledge (FCC 47 CFR 15.247/15.407, ISED RSS-247, ETSI EN 300 440 / EN 302 502)）

你的结论：

## question 1642 · needs_review · Standards overview

What happens in the definitive cases of UE-initiated inter-slice switching?

1. The UE chooses to switch slices definitely regardless of whether a suitable alternate slice is available in Allowed NSSAI.  ← 标准答案
2. The UE attempts to obtain a possible alternate slice in Allowed NSSAI through Registration for lower costs.
3. The UE releases its current session and stops receiving traffic from the current slice.
4. The UE decides to switch to an alternate slice that is already present in Allowed NSSAI.
5. The UE makes the final decision to switch slices after the successful completion of the Registration process.

盲答：Qwen 4，Claude 4

- inv1：**unverifiable** — I could not find the 'definitive cases' of UE-initiated inter-slice switching in any 3GPP text I checked. The related material in TR 23.700-41 (clause 6.42) and TR 23.700-40 (clause 6.44.3) describes network-controlled slice replacement. There, if the alternative S-NSSAI is not in the Allowed NSSAI, the UE first registers to it. That clause does not use a definitive/tentative split. The marked option 1 says the UE switches definitively whether or not an alternative slice is in the Allowed NSSAI. It is oddly specific, which suggests it may have been copied from the source text, where a 'tentative' case would be the opposite. The blind answers' option 4 (the alternative slice is already in the Allowed NSSAI) also sounds plausible. Without the primary source I can't confidently say which one is right.（来源：https://www.itecspec.com/3gpp/23.700-41/s/6.42.2 ; https://www.itecspec.com/3gpp/23.700-40/s/6.44.3 ; web searches found no text using the 'definitive cases' wording）
- inv2：**correct**（应为 1） — The question follows the framing in the arXiv paper on inter-slice mobility. The paper splits UE-initiated switching into tentative and definitive cases. In the definitive case, the UE decides to switch slices for good and leaves the current slice whether or not a suitable alternate slice is in the Allowed NSSAI. That is option 1. Option 4, an alternate slice already in the Allowed NSSAI, is only one sub-case of the definitive case. Options 2 and 5 describe the tentative case. Option 3 is a consequence, not the defining feature. This rests on a search-result summary of the paper; the PDF was not opened.（来源：arXiv:2003.11343, 'Inter-Slice Mobility Management in 5G: Motivations, Standard Principles, Challenges and Research Directions' (https://arxiv.org/pdf/2003.11343)）

你的结论：

## question 2082 · needs_review · Standards specifications

What triggers the UE to send the RRCResumeRequest message? [3GPP Release 17]

1. RNA update
2. DL data arrival
3. UL data arrival
4. RAN-based paging  ← 标准答案

盲答：Qwen 4，Claude 3

- inv1：**ambiguous** — TS 38.300/38.331: a UE in RRC_INACTIVE starts RRC resume (sending RRCResumeRequest) because of RAN-based paging, a periodic or RNA-based update, or UL data/signalling arrival. RAN paging (marked option 4) is a valid trigger, but so are RNA update (option 1) and UL data arrival (option 3). DL data reaches the UE only through RAN paging. The question does not single out one trigger.（来源：own knowledge (3GPP TS 38.300 clause 9.2.2, TS 38.331 clause 5.3.13)）
- inv2：**ambiguous** — Per TS 38.300/38.331, a UE in RRC_INACTIVE sends RRCResumeRequest on RAN-based paging (option 4), on UL data arrival (option 3) and on periodic or moving RNA update (option 1). DL data triggers paging rather than the request directly. Three options are valid triggers, so the marked option 4 is not uniquely right.（来源：3GPP TS 38.300 clause 9.2.2 / TS 38.331 clause 5.3.13 (own knowledge)）

你的结论：

## question 2224 · needs_review · Standards specifications

What does the RA field represent in a frame? [IEEE 802.11]

1. The immediate intended receiver of the frame  ← 标准答案
2. The address from the TA field of the previous frame
3. The address from the Address 2 field of the previous frame
4. The immediate intended receivers of the frame

盲答：Qwen 未跑，Claude 4

- inv1：**ambiguous** — In 802.11 the RA is the MAC address that identifies the intended immediate recipient STA(s), so it can be one receiver or several (group addressed). Option 1 (singular) and option 4 (plural) are near-duplicates and both defensible. The question names no frame type: for a CTS the RA is copied from the TA of the previous RTS (option 2), and for an Ack it is copied from Address 2 of the previous frame (option 3). The marked option 1 is reasonable but not uniquely right.（来源：own knowledge (IEEE 802.11-2020 cl. 3 definitions, 9.3.1.2-9.3.1.3)）
- inv2：**ambiguous** — IEEE 802.11 defines the RA as the MAC address of the intended immediate recipient STA(s). Because the RA can be a group address, the plural option 4 ('receivers') is as defensible as the singular option 1, which is the marked answer. The two options differ only by number, so the marked answer can't be called uniquely right.（来源：own knowledge (IEEE 802.11-2020, clause 3 definition of receiver address)）

你的结论：

## question 2367 · needs_review · Standards specifications

What authentication method does the 5G system support for legacy non-3GPP devices accessing a 5G LAN-VN? [3GPP Release 17]

1. Biometrics
2. Alternative authentication methods
3. 3GPP credentials  ← 标准答案
4. Non-3GPP identities and credentials
5. EAP framework

盲答：Qwen 2，Claude 4

- inv1：**ambiguous** — TS 22.261 clause 8.3 says the 5G network shall support a '3GPP supported mechanism' to authenticate legacy non-3GPP devices for 5G LAN-VN access. It does not say '3GPP credentials', and legacy non-3GPP devices normally have no 3GPP credentials. Option 3 looks like a garbled version of 'a 3GPP supported mechanism'. Options 4 and 5 reflect nearby requirements in the same clause about EAP and non-3GPP credentials for non-public networks. No option matches the source text exactly.（来源：3GPP TS 22.261 clause 8.3 (seen as a third-party mirror via search results: https://www.itecspec.com/3gpp/22.261/s/8.3)）
- inv2：**ambiguous** — TS 22.261 clause 8.3 requires the 5G network to support 'a 3GPP supported mechanism to authenticate legacy non-3GPP devices for 5G LAN-VN access'. It does not say 3GPP credentials. A separate requirement in the same clause covers an EAP-like framework with non-3GPP identities and credentials and alternative methods for NPN access. Option 3 is a loose paraphrase of the spec, and options 4 and 5 are also arguable, so no single option clearly matches.（来源：https://www.itecspec.com/3gpp/22.261/s/8.3）

你的结论：

## question 2442 · needs_review · Standards specifications

What does the Power Of Two Horizontal Error field indicate? [IEEE 802.11]

1. Vertical location error
2. Error between horizontal location and Latitude and Longitude fields  ← 标准答案
3. Relative horizontal error of greater than 32 m
4. Relative horizontal error
5. Usage rules of the reporting STA

盲答：Qwen 未跑，Claude 4

- inv1：**ambiguous** — This field is in an 802.11 location (LCI-related) error subelement and encodes a horizontal error as a power of two. Option 2 (error between the horizontal location and the Latitude/Longitude fields) and option 4 (relative horizontal error) both describe this same quantity in different words, so I cannot pick one uniquely without the exact clause text. I could not retrieve the standard text to check.（来源：own knowledge; web search found no primary text）
- inv2：**unverifiable** — I could not find this field name in an accessible source. My memory suggests a power-of-two encoded horizontal error field inside the LCI Relative Location Error subelement. If that is right, option 4 ('relative horizontal error') would fit better than the marked option 2, but I could not confirm the standard's wording.（来源：web search (IEEE 802.11 mentor LCI submissions); own knowledge）

你的结论：

## question 2835 · needs_review · Standards specifications

What is the purpose of NWDAF in the 5G system architecture? [3GPP Release 18]

1. To interact with different entities for data collection  ← 标准答案
2. To store and retrieve data from ADRF
3. To provide analytics to consumers
4. To exchange analytics and collect input data between PLMNs
5. To request and subscribe to trained ML model provisioning services

盲答：Qwen 未跑，Claude 3

- inv1：**ambiguous**（应为 3） — In TS 23.288 (Rel-18) clause 6, the NWDAF interacts with different entities for different purposes: data collection, retrieving data from ADRF, analytics provisioning to consumers, exchanging analytics and input data between PLMNs (roaming), and ML model provisioning (MTLF). Every option describes a real NWDAF function, so the question has more than one defensible answer. The marked option 1 seems to come from the clause's opening sentence ('interacts with different entities...'). Still, the NWDAF's core purpose in TS 23.501 is to provide analytics to NF/AF/OAM consumers (option 3), and data collection is a means to that end. Option 3 is arguably the better answer, so the marked answer cannot be called uniquely correct.（来源：own knowledge (3GPP TS 23.288 Rel-18, clause 6; TS 23.501, clause 6.2.18)）
- inv2：**ambiguous**（应为 3） — TS 23.501 clause 6.2.18 and TS 23.288 describe NWDAF as an NF that supports data collection from NFs/AFs/OAM, analytics provisioning to consumers, storing and retrieving data via ADRF, roaming (inter-PLMN) analytics exchange, and ML model provisioning (MTLF). Most options describe a real NWDAF function. The question asks for its 'purpose', and the most defensible answer to that is option 3, providing analytics to consumers. Data collection (the marked option 1) is a means to that end, not the purpose. The marked key looks like it was taken from a sentence in TS 23.288 ('NWDAF interacts with different entities for different purposes'), so it is not uniquely right; option 3 is arguably better.（来源：3GPP TS 23.501 clause 6.2.18; 3GPP TS 23.288 clauses 4-6 (own knowledge)）

你的结论：

## question 3252 · needs_review · Standards overview

What pins are used for bi-directional data transmission in Gigabit Ethernet? [IEEE 802.3]

1. Pin 5 and 6
2. Pin 1 and 2
3. Pin 3 and 6  ← 标准答案
4. Pin 7 and 8

盲答：Qwen 4，Claude 4

- inv1：**ambiguous** — 1000BASE-T sends data in both directions on all four pairs (1-2, 3-6, 4-5, 7-8). Options 2, 3 and 4 are each one of those bidirectional pairs, so none is uniquely right. Pins 3 and 6 is the 10/100BASE-T receive-pair answer, not something specific to Gigabit. The question is flawed.（来源：own knowledge (IEEE 802.3 Clause 40, 1000BASE-T)）
- inv2：**ambiguous** — 1000BASE-T (IEEE 802.3 Clause 40) sends data bidirectionally on all four pairs (pins 1-2, 3-6, 4-5 and 7-8) at once. Pins 1/2, 3/6 and 7/8 are therefore all equally valid. Option 1 (5 and 6) is not a pair. The marked answer, 3 and 6, is no more correct than options 2 or 4. The question appears to mix up 1000BASE-T with 10/100BASE-T pinouts.（来源：own knowledge (IEEE 802.3 Clause 40, 1000BASE-T)）

你的结论：

## question 4034 · needs_review · Standards overview

Why is seamless and elastic integration between MEC (Multi-access Edge Computing) applications and the cloud crucial?

1. To save back-haul capacity in the core network
2. To attract a large community of developers already used to programming client-server applications in the cloud
3. To ensure reliable connection to backend systems of car manufacturers and suppliers
4. All of the above  ← 标准答案

盲答：Qwen 4，Claude 2

- inv1：**correct**（应为 4） — The ETSI MEC automotive and edge material links tight MEC-cloud integration to three things: saving back-haul capacity, letting developers who already program client-server cloud applications build for MEC, and reliable connection to the backend systems of car makers and suppliers. Since all three options are valid reasons, 'All of the above' (option 4) is the best answer. Not checked against the exact source text.（来源：own knowledge (ETSI MEC white papers)）
- inv2：**ambiguous** — The question's wording closely matches an ETSI MEC white-paper statement giving one specific reason for seamless and elastic MEC-cloud integration: attracting the large community of developers already used to cloud client-server programming (option 2). Options 1 (saving backhaul) and 3 (connection to car makers' backends) are general MEC/automotive benefits, so 'All of the above' (marked) could be argued from an automotive-context source. I could not confirm the exact source passage, so neither answer is clearly uniquely right. I lean toward option 2.（来源：own knowledge (ETSI MEC white papers; source passage not verified)）

你的结论：

## question 4282 · needs_review · Standards specifications

What is the purpose of the MPS system? [3GPP Release 18]

1. To provide preferential treatment based on the subscription for MPS  ← 标准答案
2. To enable access and core network resources for MPS sessions
3. To assign priority levels to Service Users
4. To support Priority Data Bearer Service
5. To provide MPS for roaming Service Users

盲答：Qwen 2，Claude 2

- inv1：**correct** — TS 22.153 and TS 23.501 5.16.5 describe MPS as giving subscribed Service Users priority (preferential) treatment so they get access to resources during congestion. Option 1 states this general purpose. Option 2 is vaguer and narrower ('MPS sessions'), and options 3-5 are mechanisms or sub-features rather than the purpose. Some overlap with option 2 remains, but option 1 is the best answer.（来源：own knowledge (3GPP TS 22.153; TS 23.501 clause 5.16.5)）
- inv2：**ambiguous** — The question is generic. The MPS specs (TS 22.153; TS 23.501 clause 5.16.5) describe MPS both as giving Service Users subscription-based preferential treatment or priority and as giving priority access to access and core network resources for MPS sessions. Options 1 and 2 are both defensible, so the marked option 1 is not uniquely right.（来源：3GPP TS 22.153, TS 23.501 clause 5.16.5 (own knowledge, not fetched)）

你的结论：

## question 4524 · needs_review · Standards specifications

What is the exemption provided for prioritized services during Control Plane Congestion and Overload Control? [3GPP Release 18]

1. Exemption from RRC Connection Establishment prioritization
2. Exemption from session management congestion controls  ← 标准答案
3. Exemption from mobility management congestion controls
4. Exemption from QoS Flow load rebalancing
5. Exemption from IMC prioritization

盲答：Qwen 2，Claude 3

- inv1：**ambiguous** — TS 23.501 (prioritized services such as MPS/MCS) exempts these services from both mobility management and session management congestion controls (NAS-level MM and SM back-off). So option 2 (marked) and option 3 are equally supported. Checked from memory only, not against the spec text.（来源：own knowledge (3GPP TS 23.501 clause 5.16.5 / 5.19)）
- inv2：**ambiguous** — TS 23.501 (MPS/prioritized services) says prioritized services are exempted from both Mobility Management and Session Management congestion controls. Option 2 (SM) and option 3 (MM) are each half of that statement, so both are defensible.（来源：own knowledge (3GPP TS 23.501, priority/MPS and congestion control clauses)）

你的结论：

## question 4548 · needs_review · Standards specifications

What is the potential impact of UE/TRP PCO errors on NR carrier phase positioning accuracy? [3GPP Release 18]

1. PCO errors only impact carrier phase measurements but not positioning accuracy
2. PCO errors have a significant impact on positioning accuracy
3. PCO errors have a larger impact when using carrier phases from multiple carriers
4. PCO errors have a larger impact when using carrier phases from multiple subcarriers
5. PCO errors have a negligible impact on positioning accuracy  ← 标准答案

盲答：Qwen 未跑，Claude 2

- inv1：**unverifiable** — TR 38.859 (Rel-18 NR positioning SI) lists UE/TRP antenna PCO as one of the error sources for carrier phase positioning (sec. 6.3.1, Annex A.3, model dPCO = a*dPhi + w). The draft TR I could get has no evaluation conclusion on how large the PCO impact is. The final TR text was not reachable (3GPP/ETSI downloads blocked), so I could not confirm 'negligible' (option 5) or 'significant' (option 2).（来源：Draft 3GPP TR 38.859 v0.2.0_r4 (RAN1#110bis-e drafts folder); final TR not accessible）
- inv2：**unverifiable** — TR 38.859 (the Rel-18 positioning study) lists antenna PCO among the error sources it evaluates for carrier phase positioning. I could not find the final conclusion on how much PCO errors affect accuracy, so I can't say whether 'negligible' (5) or 'significant' (2) is right. I limited my searching on purpose to save budget.（来源：3GPP TR 38.859 draft review documents (3gpp.org/ftp TSGR1_110b-e TR38.859_review); own knowledge）

你的结论：

## question 4588 · needs_review · Standards specifications

What is a roaming broker enabled Home Environment? [3GPP Release 18]

1. A home environment that has a direct commercial agreement with different serving networks.
2. A home environment that interworks with one or more serving network operators and negotiates a commercial roaming agreement.  ← 标准答案
3. A home environment that uses fraud and cost control mechanisms to ensure charges do not exceed credit limits.
4. A home environment that is capable of operating as a roaming broker.
5. A home environment that routes registration requests to its serving networks.

盲答：Qwen 未跑，Claude 2

- inv1：**correct**（应为 2） — No standard formally defines 'roaming broker enabled Home Environment'. The phrase appears only in TS 22.115 clause 8 (Automatic Roaming Agreements). That clause says each home environment interworks with one or more serving network operators, negotiates commercial roaming agreements with them and tests the interworking, which is option 2. Option 1 contradicts the clause, which is about networks with no direct agreement. Option 3 is the cost-control requirement. Option 4 misapplies a statement about serving networks, since the clause says any serving network can act as a roaming broker. Option 5 does not match: users register with the serving network, not the HE. Option 2 is the best match, though the question rests on paraphrase rather than a formal definition.（来源：3GPP TS 22.115 clause 8 (https://itecspec.com/3gpp/22.115/s/8)）
- inv2：**ambiguous** — Neither TS 22.115 nor TS 21.905 formally defines 'roaming broker enabled Home Environment'. The question seems to be built from TS 22.115 clause 8 (automatic roaming agreements), and every option paraphrases a different sentence of that clause. Option 2 restates the general requirement that 'each Home Environment shall interwork with one or more serving network operators' by negotiating a roaming agreement. That sentence describes any HE, not specifically a roaming-broker-enabled one. Option 4 matches the literal meaning of 'roaming broker enabled', although the source says this about serving networks. With no normative definition, the marked answer can't be called uniquely right.（来源：3GPP TS 22.115 clause 8 (https://itecspec.com/3gpp/22.115/s/8); TS 22.115 clause 3.1 has no such definition）

你的结论：

## question 4759 · needs_review · Standards specifications

Which reference point replaces the Gz reference point within the common charging architecture? [3GPP Release 18]

1. Gy
2. Rf
3. Gzn
4. Ro
5. Ga  ← 标准答案

盲答：Qwen 3，Claude 3

- inv1：**ambiguous** — TS 32.240 (Fig. 4.2.2.1 NOTE): Gz is functionally equivalent to Ga for the Legacy PS domain and to one of Ga or Rf for the Evolved PS domain, and Ga/Rf are used throughout for offline charging. That makes both Ga (marked) and Rf defensible. 'Gzn' does not appear to be a real reference point. The Claude/Qwen blind answer of option 3 is not supported.（来源：3GPP TS 32.240 clause 4.2.2 (itecspec.com/3gpp/32.240/s/4.2.2)）
- inv2：**correct** — TS 32.240/32.251 state that the Gz reference point is functionally equivalent to Ga and is replaced by Ga within the common charging architecture. Gzn is not a real reference point, and Ro/Rf/Gy are online or Diameter offline interfaces, not the replacement.（来源：3GPP TS 32.240 / TS 32.251 (own knowledge)）

你的结论：

## question 4873 · needs_review · Standards specifications

What type of uncertainty assessment is performed for the measurement uncertainty budget of UE RF testing methodology? [3GPP Release 18]

1. Static propagation conditions
2. Multi-path fading propagation conditions
3. Uncertainty assessment  ← 标准答案
4. Polarization basis mismatch between the TE and DUT
5. Inter-band (FR2+FR2) CA

盲答：Qwen 1，Claude 3

- inv1：**ambiguous** — The question is flawed. The marked option 3, 'Uncertainty assessment', just repeats the question's own wording rather than naming a type of assessment. Options 1 and 2 (static vs. multi-path fading propagation conditions) are the real kinds of measurement-uncertainty-budget assessment in the UE RF/OTA testing TRs, so the question has no unique, meaningful answer.（来源：own knowledge (3GPP TR 38.810-family UE RF test methodology MU budgets)）
- inv2：**ambiguous** — The question is circular. The marked option, 'Uncertainty assessment', just repeats the question's wording. The other options (static or multipath propagation conditions, polarisation mismatch, inter-band CA) look like the different conditions or contributors that TR 38.903-style MU budgets assess. The item seems to have been generated poorly from a heading, so no option is clearly and uniquely correct.（来源：own knowledge (3GPP TR 38.903 NR UE RF measurement uncertainty)）

你的结论：

## question 4970 · needs_review · Standards specifications

What is the purpose of code-bit interleaving? [IEEE 802.15.4]

1. To increase the data rate of the transmission
2. To improve the robustness of the transmission
3. To reduce the power consumption of the transmission
4. To ensure the synchronization of the transmitter and receiver
5. To mitigate the effects of fading and interference  ← 标准答案

盲答：Qwen 2，Claude 2

- inv1：**ambiguous**（应为 2） — MR-FSK FEC text (802.15.4g, carried into 802.15.4-2015/2020) says code-bit interleaving is used 'to improve robustness against burst errors' and to break correlation of consecutive bits. That matches option 2's wording. Option 5 (mitigate fading/interference, which cause burst errors) is also defensible, so the marked option 5 is not uniquely right; option 2 is closer to the standard's text.（来源：IEEE 802.15 doc 15-10-0182-02-004g (MR-FSK unified FEC text); https://mentor.ieee.org/802.15/dcn/12/15-12-0134-00-004k-proposal-on-fsk-phy-interleaver.pdf）
- inv2：**ambiguous** — In IEEE 802.15.4 PHYs (for example LECIM DSSS and SUN modes), code-bit interleaving spreads coded bits to guard against burst errors from fading and interference, which improves robustness. Option 2 (improve robustness) and option 5 (mitigate fading and interference) describe the same purpose at different levels of detail, so both can be defended. The exact standard wording could not be checked because the web search hit its session limit.（来源：own knowledge）

你的结论：

## question 5467 · needs_review · Standards specifications

How long can the SDT procedure last? [3GPP Release 18]

1. As long as there is data to transmit.
2. Until the DL RSRP goes below a configured threshold.
3. Until a SDT failure detection timer expires.  ← 标准答案
4. Until the UE transitions to RRC_IDLE state.
5. Until the network sends an RRCRelease message.

盲答：Qwen 未跑，Claude 5

- inv1：**ambiguous** — In Rel-18 NR SDT (TS 38.300 clause 18, TS 38.331), the SDT procedure normally ends when the network sends RRCRelease. That is option 5 (the UE stays in or goes back to RRC_INACTIVE). The SDT failure detection timer (T319a) starts when SDT begins and stops when RRCRelease arrives; if it expires, the procedure fails, so the timer only sets the failure bound. Options 3 and 5 can both be defended for 'how long can it last'. Option 5 is arguably better, since that is how the procedure normally ends. Web search was unavailable, so I could not confirm the exact source sentence.（来源：own knowledge (3GPP TS 38.300 clause 18; TS 38.331 T319a)）
- inv2：**ambiguous** — Per TS 38.300 clause 18 and TS 38.331, the UE stays in RRC_INACTIVE during SDT. The network normally ends the procedure with RRCRelease. The SDT failure detection timer (T319a) starts when SDT is initiated, and if it expires the UE moves to RRC_IDLE. So both option 3 (the timer, the marked answer) and option 5 (RRCRelease) can be defended. The question does not say whether it means normal termination or the maximum duration. Web search was unavailable (session limit), so I could not confirm the exact source wording.（来源：own knowledge (TS 38.300 cl.18, TS 38.331 T319a)）

你的结论：

## question 5608 · needs_review · Standards specifications

Besides the short service definition and description of normal operation, what other information is provided for each supplementary service? [3GPP Release 17]

1. Exceptional operation or unsuccessful outcome
2. Interworking with other supplementary services
3. Interaction with PSTN/ISDN and CS mobile networks
4. Consideration for interworking with CS mobile and fixed services  ← 标准答案
5. Mandatory or optional support based on regulations

盲答：Qwen 1，Claude 1

- inv1：**ambiguous** — TS 22.173 clause 8.1 says each supplementary service gives a short definition and a description of normal operation. Where relevant it also covers exceptional or unsuccessful operation, interactions with other IMS supplementary services, and consideration for interworking with CS mobile and fixed services. Options 1 and 4 both appear in the spec text, and option 2 roughly matches too, so the marked option 4 is not the only right answer.（来源：3GPP TS 22.173 clause 8.1 (itecspec.com/3gpp/22.173/s/8.1)）
- inv2：**correct** — TS 22.173 (IMS Multimedia Telephony service and supplementary services) introduces each supplementary service with a short service definition, a description of normal operation, and considerations for interworking with CS mobile and fixed services. Option 4 uses that wording. Option 3 is close but is not the spec's phrasing. This is recalled, not checked against the text.（来源：3GPP TS 22.173 (own knowledge)）

你的结论：

## question 6912 · needs_review · Standards specifications

What are the possible classifications of OFDM symbols in a slot in a downlink frame? [3GPP Release 17]

1. 'downlink', 'flexible', or 'uplink'
2. 'downlink' or 'flexible' symbols  ← 标准答案
3. 'uplink' or 'flexible' symbols
4. 'downlink' or 'uplink' symbols

盲答：Qwen 2，Claude 1

- inv1：**ambiguous** — TS 38.211 clause 4.3.2 says OFDM symbols in a slot can be classified as 'downlink', 'flexible' or 'uplink' (option 1). The next sentence says that in a slot in a downlink frame, the UE assumes downlink transmissions only occur in 'downlink' or 'flexible' symbols (option 2). Read literally, the question asks for the classifications, which points to option 1. The marked option 2 matches the downlink-frame sentence instead, so the wording mixes the two statements.（来源：own knowledge (3GPP TS 38.211 clause 4.3.2; TS 38.213 clause 11.1)）
- inv2：**wrong**（应为 1） — TS 38.211 clause 4.3.2 says OFDM symbols in a slot can be classified as 'downlink', 'flexible', or 'uplink'. The phrase 'downlink' or 'flexible' comes from the next sentence: in a slot in a downlink frame, the UE assumes DL transmissions occur only in downlink or flexible symbols. That sentence is about where DL transmissions happen, not about the set of classifications. So the question as written asks for the classification set, which is option 1.（来源：own knowledge (3GPP TS 38.211 Rel-17, clause 4.3.2)）

你的结论：

## question 7657 · needs_review · Standards specifications

Which component handles the request for prioritized QoS Flows for Mobile Originations? [3GPP Release 18]

1. AMF
2. PCF  ← 标准答案
3. UPF
4. SMF
5. (R)AN

盲答：Qwen 4，Claude 4

- inv1：**unverifiable** — TS 23.501 clause 5.16.5 on MPS splits priority handling across functions: the (R)AN handles the RRC establishment cause, the AMF/SMF apply subscription-based priority, and the PCF sets ARP/5QI for MPS QoS Flows. I could not check the exact sentence that assigns handling of requests for prioritized QoS Flows for Mobile Originations, and web search was unavailable. So I cannot confirm whether PCF (marked) or SMF is right.（来源：own knowledge (3GPP TS 23.501 clause 5.16.5, TS 23.502); not verified against text）
- inv2：**unverifiable** — This appears to come from the MPS/priority-mechanism text in TS 23.501. The PCF plausibly sets the prioritized QoS (ARP/5QI) based on the MPS subscription, but the SMF could also be described as handling the request. Without checking the exact clause I cannot confirm which component the spec names. Web search was unavailable (session limit).（来源：own knowledge (TS 23.501 clause 5.16.5 / 5.22); not verified）

你的结论：

## question 8200 · needs_review · Standards specifications

What message does the AMF send to the NG-RAN during mobility registration, AM policy modification, and handover procedures? [3GPP Release 18]

1. 5G access stratum time distribution indication
2. Uu time synchronization error budget
3. Clock quality detail level
4. UE Context Modification Request  ← 标准答案
5. N2 connection

盲答：Qwen 2，Claude 1

- inv1：**ambiguous** — Rel-18 time-sensitive/time synchronization text in TS 23.501 §5.27.1 and TS 23.502 says that during registration, AM policy modification and handover, the AMF gives NG-RAN the 5G access stratum time distribution indication, the Uu time synchronization error budget and (Rel-18) the clock quality detail level. That makes options 1, 2 and 3 the information items sent, and they arrive inside different NGAP messages: Initial Context Setup or Registration Accept N2 for registration, Handover Request for handover, and UE Context Modification Request only for AM policy modification. Option 4 is only one of those carrier messages, so it is not uniquely right, and more than one other option can be defended. The question looks auto-generated and flawed.（来源：own knowledge (3GPP TS 23.501 §5.27.1.x; TS 23.502 §4.2.4 / §4.15.9, Rel-18)）
- inv2：**ambiguous** — TS 23.501 5.27.1.9 (Rel-18) says the AMF may give NG-RAN both the 5G access stratum time distribution indication and the Uu time synchronization error budget during handover, service request, mobility registration and AM policy modification. The clause does not name UE Context Modification Request (the marked option 4). In those procedures this information would travel in different N2 messages, for example Handover Request during handover. So the marked answer has no direct support. The question was probably built from this clause, which makes option 1 the likely intended answer. But option 2 is also sent in the same procedures, so no single option is uniquely correct. The question itself is flawed: it asks for a 'message' while the options mix information elements with NGAP messages.（来源：3GPP TS 23.501 clause 5.27.1.9 and 5.27.1.11, plus TS 23.502 4.28.2.1. Read through the mirrors https://www.itecspec.com/3gpp/23.501/s/5.27.1.9 and https://itecspec.com/3gpp/23.501/s/5.27.1.11）

你的结论：

## question 8405 · needs_review · Standards specifications

What service does AF invoke to request the DNAI information? [3GPP Release 18]

1. NEF service Nnef_DNAIMapping_Subscribe
2. Nudr_DM_Subscribe
3. UDR notifies the NEF
4. Nnef_DNAIMapping_Subscribe  ← 标准答案

盲答：Qwen 1，Claude 1

- inv1：**ambiguous** — In TS 23.548 the AF requests DNAI information by invoking the NEF service Nnef_DNAIMapping_Subscribe. Options 1 and 4 name that same service, with and without the words "NEF service", so both are correct. The marked option 4 is right, but it is not the only right answer.（来源：own knowledge (3GPP TS 23.548 Rel-18, DNAI mapping procedure)）
- inv2：**ambiguous** — Options 1 ('NEF service Nnef_DNAIMapping_Subscribe') and 4 ('Nnef_DNAIMapping_Subscribe') name the same NEF service operation; both are equally correct, so the marked option 4 is not uniquely right.（来源：own knowledge (3GPP TS 23.548 / TS 23.502 Rel-18 NEF DNAI mapping service)）

你的结论：

## question 8841 · needs_review · Standards specifications

What is SAR in perfect adiabatic conditions? [IEEE C95.1]

1. The rate of heat production in tissue exposed to RF energy
2. The rate of temperature change in tissue exposed to RF energy
3. The rate of RF energy absorption in tissue  ← 标准答案
4. The rate of heat loss in tissue exposed to RF energy
5. The specific heat capacity of tissue

盲答：Qwen 2，Claude 2

- inv1：**ambiguous** — IEEE C95.1 defines SAR as the rate of RF energy absorption per unit mass (option 3). A note adds that under perfect adiabatic conditions (no heat loss), SAR = c·dT/dt, so it is tied to the rate of temperature rise (option 2, though that option leaves out the specific heat c). The phrase 'in perfect adiabatic conditions' points the question toward option 2, while option 3 is the general definition and is always true. Both options can be defended.（来源：own knowledge (IEEE Std C95.1-2019 SAR definition and note)）
- inv2：**ambiguous** — Option 3 (rate of RF energy absorption) is SAR's general definition and holds regardless of conditions. The phrase 'in perfect adiabatic conditions' points to the C95.1 note relating SAR to the rate of temperature rise (SAR = c dT/dt), which suggests option 2 is the intended answer. Option 1 (rate of heat production) is also defensible under adiabatic conditions. SAR is proportional to dT/dt rather than equal to it, so no single option is clearly the unique answer.（来源：own knowledge of IEEE C95.1 SAR definition; FCC SAR appendices (fcc.report) on SAR = c dT/dt）

你的结论：

## question 8988 · needs_review · Standards specifications

What rate selection rules apply to group addressed Data and Management frames transmitted by CMMG STAs? [IEEE 802.11]

1. The MCS used for transmission should be an MCS common to the supported MCS sets of all receivers  ← 标准答案
2. The MCS used for transmission should be an MCS from the mandatory MCS set of the CMMG control or SC mode
3. The rate selection rules follow the same rules as individually addressed frames
4. The rate selection rules do not apply to group addressed frames

盲答：Qwen 未跑，Claude 2

- inv1：**ambiguous** — 802.11 rate selection rules for DMG/CMMG group addressed frames usually tie the MCS to the mandatory MCS set of the control/SC mode, which supports option 2. Option 1 (an MCS common to all receivers' supported sets) is the generic group-addressed rule and is also defensible. A web search turned up only TGaj working documents, not the published clause text, so I could not settle which one is right.（来源：Web search of IEEE 802.11 TGaj documents (e.g. 11-20-0823, 11-16-1333 MDR report); own knowledge）
- inv2：**unverifiable** — Options 1 and 2 both read like plausible 802.11 rate-selection text. Option 2's specific wording ('mandatory MCS set of the CMMG control or SC mode') matches the style of the DMG/CMMG group-addressed rules in IEEE 802.11-2020 clause 10.6, which makes the marked option 1 doubtful. A web search did not turn up the CMMG group-addressed subclause text, so I cannot confirm either option.（来源：Web search for IEEE 802.11-2020 clause 10.6 CMMG rate selection; only 11aj comment-resolution docs found, e.g. https://bibliotheek.ehb.be:3499/802.11/dcn/20/11-20-0823-01-000m-proposed-resolution-for-cid-4505.docx）

你的结论：

## question 9037 · needs_review · Standards overview

What information is forwarded by the transport network for UAS (unmanned aircraft system) nodes in remote identification?

1. UAV identity, its capability as a user equipment (UE), make and model, serial number, take-off weight, position, owner information, take-off location, mission type, flight data, and operation status.  ← 标准答案
2. Controller identity, its capability as a user equipment (UE), controller position, owner, operator and pilot information, and flight plan.
3. UAS identification and subscription information for discriminating between UAS capable UE and non-UAS capable, or regular, UEs.
4. Additional data that may be relevant to the UTM after successful authentication and authorization.
5. Live position information updates of the UAV and its controller.

盲答：Qwen 3，Claude 1

- inv1：**ambiguous** — TS 22.125 lists the data the 3GPP system forwards to the UTM for remote ID. UAV data matches option 1 and UAV-controller data matches option 2. The question asks about 'UAS nodes', which covers both, so option 1 is only part of the answer and option 2 is equally defensible.（来源：own knowledge (3GPP TS 22.125 cl. 5.1)）
- inv2：**ambiguous** — TS 22.125 (Rel-16 remote identification of UAS) requires the 3GPP system to forward UAV data to the UTM: identity, UE capability, make/model, serial number, take-off weight, position, owner info, take-off location, mission type, route data and operating status. It also requires forwarding UAV controller data: identity, UE capability, position, owner/operator/pilot info and flight plan. Option 1 and option 2 are therefore both forwarded information. The question does not say which entity it means.（来源：own knowledge (3GPP TS 22.125 Rel-16, remote identification requirements; TR 21.916)）

你的结论：

## question 9533 · needs_review · Standards specifications

What is the purpose of UE categories in NR? [3GPP Release 18]

1. To define UE capabilities
2. To determine peak data rates  ← 标准答案
3. To signal to the network
4. To support different functionalities
5. To advertise alternative features

盲答：Qwen 4，Claude 2

- inv1：**ambiguous** — NR (TS 38.306) mostly defines UE capabilities through individual capability signalling rather than LTE-style categories. Both 'define UE capabilities' (option 1) and 'determine peak data rates' (option 2) are defensible readings, and option 4 overlaps with them too. No single option is clearly the uniquely right one.（来源：own knowledge (TS 38.306 / TS 36.306 category concept); web search unavailable (session limit)）
- inv2：**ambiguous** — In NR (TS 38.306), peak data rates come from a formula based on the capabilities the UE signals, not from LTE-style UE categories. Option 2 matches the LTE-style purpose of categories, but option 1 ('to define UE capabilities') is just as defensible. The options are vague and overlap.（来源：own knowledge (TS 38.306, TS 36.306); web search unavailable）

你的结论：

## question 3851 · suspect_wrong · Standards overview

What is the purpose of IGMP snooping? [TCP/IP]

1. To configure multicast groups manually
2. To translate multicast IP addresses to multicast MAC addresses  ← 标准答案
3. To filter multicast messages in Layer 2-based networks
4. To improve network traffic predictability and reliability
5. To manage network traffic efficiently

盲答：Qwen 3，Claude 3

- inv1：**wrong**（应为 3） — IGMP snooping is a Layer-2 switch feature: the switch listens to IGMP messages so it can forward multicast frames only to ports with interested receivers instead of flooding them. Option 3 says this. Mapping multicast IP addresses to MAC addresses (the marked option 2) is the fixed IP-to-MAC mapping in RFC 1112, not IGMP snooping. Option 5 is generic and also true in a loose sense, but option 3 is the clearly best answer.（来源：own knowledge (RFC 4541; RFC 1112 sec. 6.4)）
- inv2：**wrong**（应为 3） — IGMP snooping lets a Layer-2 switch listen to IGMP messages and forward or filter multicast frames only to ports with interested receivers, so it filters multicast in L2 networks. Mapping multicast IP addresses to MAC addresses (the marked option 2) is a fixed address mapping defined in RFC 1112, not what IGMP snooping does.（来源：RFC 4541 (IGMP/MLD snooping considerations); own knowledge）

你的结论：

## question 4406 · suspect_wrong · Lexicon

What is the definition of a conventional network?

1. A network that supports national and international roaming
2. A network where multiple serving operators share at least a radio access network
3. A network that consists of a core network only
4. A network that provides services to subscribers of other operators  ← 标准答案
5. A network that supports network sharing

盲答：Qwen 1，Claude 1

- inv1：**wrong**（应为 1） — TS 23.251 §3.1 defines a conventional network as a PLMN with its own RAN and core network. In it, only one serving operator serves its own subscribers, and other operators' subscribers get service only through national and international roaming. Option 4 (the marked answer) reverses this, because the definition is centred on serving the operator's own subscribers. Option 2 is the definition of 'Core network operator' in a shared network. Option 1 is the only option that uses the definition's own roaming wording, so it is the best match, although it is a partial paraphrase. If option 1's incompleteness counts against it, 'ambiguous' is defensible.（来源：3GPP TS 23.251 §3.1, via the itecspec.com/3gpp/23.251/s/3.1 mirror and a search summary that also cited SP-040527. The 3GPP text itself was not opened.）
- inv2：**wrong**（应为 1） — TS 23.251 clause 3.1 defines a conventional network as a PLMN made of a RAN and a core network, through which only one serving operator serves its own subscribers. Subscribers of other operators may get service through national or international roaming. Option 1 (supports national and international roaming) is the option that matches this definition. Option 4 (provides services to subscribers of other operators) misses the defining point that a single serving operator serves its own subscribers; other operators' subscribers are reached only through roaming. Options 2 and 5 describe shared networks, and option 3 is wrong because the definition includes a RAN. Option 1 is not a full paraphrase either, but it is the best fit. This is a TeleQnA-style option set built from the definition text, so the call leans toward 1 rather than ambiguous.（来源：3GPP TS 23.251 clause 3.1 (https://www.itecspec.com/3gpp/23.251/s/3.1; Rel-6 text in SP-040527)）

你的结论：

## question 4536 · suspect_wrong · Standards specifications

What does DRL stand for in the context of the document? [IEEE C95.1]

1. Dangerous Radiation Levels
2. Dose Rate Limit  ← 标准答案
3. Disaster Recovery Log
4. Data Retrieval Language
5. Digital Rights Licensing

盲答：Qwen 未跑，Claude 2

- inv1：**wrong** — In IEEE C95.1-2019, DRL means 'dosimetric reference limit', the term that replaced 'basic restriction', alongside ERL (exposure reference level). 'Dose Rate Limit' (option 2) is not the expansion the standard uses. It is only the closest distractor, and none of the options is literally correct.（来源：IEEE C95.1-2019 abstract (https://ieeexplore.ieee.org/document/8859679); IEEE ICES presentation (https://ewh.ieee.org/r6/oeb/lm/previous_meetings/2019/Chou%20May%2029%202019.pdf)）
- inv2：**wrong** — In IEEE C95.1-2019, DRL means 'dosimetric reference limit' (it replaced the older term 'basic restriction'). None of the options matches. 'Dose Rate Limit' is the closest wording but is not the standard's term.（来源：own knowledge (IEEE Std C95.1-2019, definitions/acronyms)）

你的结论：

## question 7370 · suspect_wrong · Standards specifications

What is the maximum number of MR-DC combinations for IDC? [3GPP Release 17]

1. 256
2. 64
3. 512  ← 标准答案
4. 128
5. 1024

盲答：Qwen 未跑，Claude 4

- inv1：**wrong**（应为 4） — TS 38.331 defines maxCombIDC-r16 INTEGER ::= 128, commented as the maximum number of reported MR-DC combinations for IDC. It is used by affectedCarrierFreqCombListMRDC. So the answer is 128 (option 4), not 512.（来源：own knowledge (3GPP TS 38.331 multiplicity constants, maxCombIDC)）
- inv2：**wrong**（应为 4） — TS 38.331 defines maxNrofCombIDC INTEGER ::= 128, with the comment 'Maximum number of reported MR-DC combinations for IDC'. That makes the answer 128 (option 4), not 512.（来源：own knowledge (TS 38.331 multiplicity constants, maxNrofCombIDC)）

你的结论：
