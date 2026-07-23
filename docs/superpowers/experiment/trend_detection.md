Goal:

Define metrics that will separate points marked by strong (up/down) move RSI class into two classes. One class will have mostly points that are better for opening short position (short class). Other class will contain points that are better for opening/hold long position (long class).

Experiment.
- separately execute search for strong up RSI points and strong down RSI points

- mark each point if it should go to the short or long class


- look across different indicators and try to find corelation with two  desired classes. 

- look across different indicators from higher tf and try to find corelation with two  desired classes. 

- look across different indicators from lower tf and try to find corelation with two desired classes. 

- look across different levels. if the price if near any level, 

- if the movement on higher tf requires current tf to be in strong move

- if the price goes out of bound, out of bounds on higher tf,

- if the price is at the opposite bound of higher tf

- how much time left in higher tf to perform bound touch - if it requires permanent move without corrections 

- Run classification algorithms on indicators  


Results:
- List the potential hypotesys to experiment with
- provide reports with charts and metircs and dependencies that will show how good this metric splits the classes
- select best performers
- rationale how the metric can be improved
- implement the improvemnt
- if the improvement is good, apply it a and repeat the loop with improvement untill you get no improvemnts
- on each loop iteration create corresponding report
- select the best metrics the performs the best classification split

Constains:
- work in separate branch
- do not commit anything
- do not recalculate existign dataframes
- if new data required: calculate them as a separate columns and concatanate to the existign dataframe
- perfrom search for tf 15, 60, 240
- use 2y dataset for training 
- use 2m oos dataset for validation
