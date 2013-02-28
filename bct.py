
"""
bct v0.01

Bitcoin Trade Simulator

Copyright 2011 Brian Monkaba

This file is part of ga-bitbot.

    ga-bitbot is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    ga-bitbot is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with ga-bitbot.  If not, see <http://www.gnu.org/licenses/>.
"""

import pdb
import time
from operator import itemgetter
from math import exp
import sys
import paths
from cache import *

class trade_engine:
    def __init__(self):
        self.cache = cache()
        #configurable variables
        self.input_file_name = "./datafeed/bcfeed_mtgoxUSD_1min.csv"    #default input file
        self.score_only = False     #set to true to only calculate what is required for scoring a strategy
                        #to speed up performance.
        self.shares = 0.1       #order size
        self.wll = 180          #window length long
        self.wls = 2        #window length short
        self.buy_wait = 0       #min sample periods between buy orders
        self.buy_wait_after_stop_loss = 6   #min sample periods between buy orders
                            #after a stop loss order
        self.markup = 0.01      #order mark up
        self.stop_loss = 0.282      #stop loss
        self.enable_flash_crash_protection = True   #convert a stop loss order into a short term hold position
        self.flash_crash_protection_delay = 180 #max_hold in minutes
        self.stop_age = 10000       #stop age - dump after n periods
        self.macd_buy_trip = -0.66  #macd buy indicator
        self.min_i_pos = 0      #min periods of increasing price
                        #before buy order placed

        self.min_i_neg = 0      #min periods of declining price
                        #before sell order placed

        self.stbf = 2.02        #short trade biasing factor
                        #-- increase to favor day trading
                        #-- decrease to 2 to eliminate bias

        self.nlsf = 5.0         #non-linear scoring factor - favor the latest trades
                        #max factor = exp(self.nlsf) @ the last sample periord

        self.commision = 0.006      #mt.gox commision

        self.quartile = 1       #define which market detection quartile to trade on (1-4)
        self.input_data = []
        self.input_data_length = 0
        self.market_class = []
        self.current_quartile = 0
        self.classified_market_data = False
        self.max_data_len = 1000000
        self.reset()
        return

    def load_input_data(self):
        print "bct: loading input data"
        self.input_data = self.cache.get('input_data')
        if self.input_data == None:
            f = open(self.input_file_name,'r')
            d = f.readlines()
            f.close()

            if len(d) > self.max_data_len:
                #truncate the dataset
                d = d[self.max_data_len * -1:]

            self.input_data = []
            for row in d[1:]:
                r = row.split(',')[1] #last price
                t = row.split(',')[0] #time
                self.input_data.append([int(float(t)),float(r)])

            self.cache.set('input_data',self.input_data)
            self.cache.expire('input_data',60*8)

        self.input_data_length = len(self.input_data)
        return self.input_data

    def initialize(self):
        print "bct: initializing"
        self.load_input_data()
        cm = self.cache.get('classify_market')
        if cm == None:
            print "bct: classifying market data..."
            self.classify_market(self.input_data)
            self.cache.set('classify_market',self.market_class)
            self.cache.expire('classify_market',60*8)
        else:
            print "bct: cached data found."
            self.market_class = cm
            self.classified_market_data = True
        return self.current_quartile

    def run(self):
        for i in self.input_data:
            self.input(i[0],i[1])
        return

    def reset(self):
        #metrics and state variables
        self.history = []           #moving window of the inputs
        self.period = 0             #current input period
        self.time = 0               #current period timestamp
        self.input_log = []         #record of the inputs
        self.wl_log = []            #record of the wl
        self.ws_log = []            #record of the ws
        self.macd_pct_log = []
        self.buy_log = []
        self.sell_log = []
        self.stop_log = []
        self.net_worth_log = []
        self.trigger_log = []
        self.balance = 1000         #account balance
        self.opening_balance = self.balance #record the starting balance
        self.score_balance = 0          #cumlative score
        self.text_summary = ""
        self.buy_delay = 0          #delay buy counter
        self.buy_delay_inital = self.buy_delay  #delay buy counter
        self.macd_pct = 0
        self.macd_abs = 0
        self.avg_wl = 0
        self.avg_ws = 0
        self.ema_short = 0
        self.ema_long = 0
        self.i_pos = 0              #periods of increasing price
        self.i_neg = 0              #periods of decreasing price
        self.positions_open = []        #open order subset of all trade positions
        self.positions = []         #all trade positions
        self.metric_macd_pct_max = -10000   #macd metrics
        self.metric_macd_pct_min = 10000
        self.wins = 0
        self.loss = 0
        self.order_history = "NOT GENERATED"
        self.current_quartile = 0
        return

    def test_quartile(self,quartile):
        #valid inputs are 1-4
        self.quartile = quartile / 4.0

    def classify_market(self,input_list):
        #print "start market classify"
        #market detection preprocessor splits the input data into
        #quartiles based on the true range indicator

        self.market_class = []
        atr_depth = 60 * 1 #one hour atr

        #print "calc the true pct range indicator"
        last_t = 0
        last_tr = 0
        t = 0
        tr = 0
        for i in xrange(len(input_list)):
            t,p = input_list[i]
            t = int(t * 1000)
            if i > atr_depth + 1:
                dsp = [r[1] for r in input_list[i - atr_depth - 1:i]]   #get the price data set
                dsp_min = min(dsp)
                dsp_max = max(dsp)
                tr = (dsp_max - dsp_min) / dsp_min #put in terms of pct chg
                self.market_class.append([t,tr])
                last_t = t
                last_tr = tr
            else:
                #pad out the initial data
                self.market_class.append([t,0])

        #pad the end of the data to support future order testing
        for i in xrange(10):
            self.market_class.append([t,tr])

        #I was overthinking again...
        quartiles = []
        l = [r[1] for r in self.market_class]
        l.sort()
        quartiles.append(l[int(len(l) * 0.25)])
        quartiles.append(l[int(len(l) * 0.50)])
        quartiles.append(l[int(len(l) * 0.75)])

        #and apply them to the market class log
        for i in xrange(len(self.market_class)):
            p = self.market_class[i][1]
            self.market_class[i][1] = 0.25
            if p > quartiles[0]:
                self.market_class[i][1] = 0.50
            if p > quartiles[1]:
                self.market_class[i][1] = 0.75
            if p > quartiles[2]:
                self.market_class[i][1] = 1.0
            if i < atr_depth + 1:
                self.market_class[i][1] = 0.0   #ignore early (uncalculated) data
        self.classified_market_data = True
        self.current_quartile = int(self.market_class[len(self.market_class)-1][1] * 4) #return the current quartile (1-4)
        return self.current_quartile

    def metrics_report(self):
        m = ""
        m += "\nShares: " + str(self.shares)
        m += "\nMarkup: " + str(self.markup * 100) + "%"
        m += "\nStop Loss: " + str(self.stop_loss * 100) + "%"
        m += "\nStop Age: " + str(self.stop_age)
        m += "\nBuy Delay: " + str(self.buy_wait)
        m += "\nBuy Delay After Stop Loss: " + str(self.buy_wait_after_stop_loss)
        m += "\nMACD Trigger: " + str(self.macd_buy_trip) + "%"
        m += "\nEMA Window Long: " + str(self.wll)
        m += "\nEMA Window Short: " + str(self.wls)
        m += "\niPos: " + str(self.i_pos)
        m += "\niNeg: " + str(self.i_neg)
        m += "\nShort Trade Bias: " + str(self.stbf)
        m += "\nCommision: " + str(self.commision * 100) + "%"
        m += "\nScore: " + str(self.score())
        m += "\nTotal Periods : " + str(self.period)
        m += "\nInitial Buy Delay : " + str(self.buy_delay_inital)
        m += "\nOpening Balance: $" + str(self.opening_balance)
        m += "\nClosing Balance: $" + str(self.balance)
        m += "\nTransaction Count: " + str(len(self.positions))
        m += "\nWin: " + str(self.wins)
        m += "\nLoss: " + str(self.loss)
        try:
            m += "\nWin Pct: " + str(100 * (self.wins / float(self.wins + self.loss))) + "%"
        except:
            pass
        m += "\nMACD Max Pct: " + str(self.metric_macd_pct_max)+ "%"
        m += "\nMACD Min Pct: " + str(self.metric_macd_pct_min)+ "%"
        return m

    def dump_open_positions(self):
        #dump all active trades to get a current balance
        self.positions_open = [] #clear out the subset buffer
        for position in self.positions:
            if position['status'] == "active":
                position['status'] = "dumped"
                position['actual'] = self.history[1]    #HACK! go back in time one period to make sure we're using a real price
                                    #and not a buy order target from the reporting script.
                position['sell_period'] = self.period
                self.balance += position['actual'] * (position['shares'] - (position['shares'] * self.commision))
            if position['age'] > 0:
                self.score_balance += ((position['actual'] * (position['shares'] - (position['shares'] * self.commision))) / (position['buy'] * (position['shares'] + 0.0001))) * (pow(position['age'],self.stbf) / position['age'] )

    def score(self):
        self.dump_open_positions()
        if (self.wins + self.loss) > 0:
            self.positions = sorted(self.positions, key=itemgetter('buy_period'))
            exp_scale = self.nlsf / self.period #float(self.positions[-1]['buy_period'])
            final_score_balance = 0
            for p in self.positions:
                p['score'] = 0
                if p['status'] == "sold":
                    p['age'] = float(p['age'])
                    p['score'] = (((p['target'] - p['buy']) / p['buy']) * 100.0 ) * self.shares
                    #apply non-linear scaling to the trade based on the round trip time (age)
                    #favors a faster turn around time on positions
                    p['score'] /= (pow(p['age'],self.stbf) / p['age'] )
                    p['score'] *= 10.0
                    if p['age'] < 4.0:
                        p['score'] *= (1/4.0) #I'm knocking down very short term trades because there's a chance the system will miss them in live trading
                if p['status'] == "stop":
                    if p['actual'] > p['buy']:
                        age = float(self.stop_age)
                        #if there wasn't a loss caused by the stop order
                        p['score'] = (((p['buy'] - p['actual']) / p['buy']) * 100.0)  * self.shares
                        #apply non-linear scaling to the trade based on the round trip time (age)
                        #favors a faster turn around time on positions
                        p['score'] /= (pow(age,self.stbf) / age )
                        p['score'] *= 100.0
                    else:
                        #losing position gets a negative score
                        age = float(self.stop_age)
                        p['score'] = ((((p['actual'] - p['buy']) / p['buy']) * 100.0)  * self.shares)
                        #apply non-linear scaling to the trade based on the round trip time (age)
                        #favors a faster turn around time on positions
                        p['score'] /= ((pow(age,self.stbf) / (age + 0.000001) ) + 0.0001)
                        p['score'] *= 1000.0    #increase weighting for losing positions

                #apply e^0 to e^1 weighting to favor the latest trade results
                p['score'] *= exp(exp_scale * p['buy_period'])
                final_score_balance += p['score']


            #because stop loss will generaly be higher that the target (markup) percentage
            #the loss count needs to be weighted by the pct difference
            loss_weighting_factor = self.stop_loss / self.markup

            final_score_balance *= self.wins / (self.wins + (self.loss * loss_weighting_factor) * 1.0)
            #final_score_balance *= self.markup * len(self.positions)

            #fine tune the score
            final_score_balance -= self.buy_wait / 1000.0
            final_score_balance -= self.buy_wait_after_stop_loss / 1000.0
            final_score_balance -= (self.stop_loss * 1000)
            final_score_balance += (self.wls / 1000.0)
            final_score_balance -= (self.stop_age / 1000.0)
            final_score_balance += self.shares

            #severly penalize the score if the win/ratio is less than 75%
            if self.wins / (self.wins + self.loss * 1.0) < 0.75:
                final_score_balance /= 10000.0

            #risk reward weighting
            if final_score_balance > 0:
                rr = self.markup / (self.stop_loss + 0.00001)
                #clamp the risk reward weighting
                if rr > 2.0:
                    rr = 2.0
                final_score_balance *= rr


            #if self.opening_balance > self.balance:
            #   #losing strategy
            #   final_score_balance -= 5000 #999999999
        else:
            #no trades generated
            final_score_balance = -987654321.123456789

        #create the text_summary of the results
        self.text_summary = "Balance: " + str(self.balance) +"; Wins: " + str(self.wins)+ "; Loss:" + str(self.loss) +  "; Positions: " + str(len(self.positions))
        return final_score_balance

    def ai(self):
        #make sure the two moving averages (window length long and short) don't get inverted
        if self.wll < self.wls:
            self.wll += self.wls
        #decrement the buy wait counter
        if self.buy_delay > 0:
            self.buy_delay -= 1
        #place buy orders, set price targets and stop loss limits
        current_price = self.history[0]
        #if the balance is sufficient to place an order and there is no buy delay
        buy = current_price * -1
        #but only if the classified input data matches the quartile assigned
        #OR if the input data was not pre-classified in which case quartile partitioning is disabled.
        if self.classified_market_data == False or self.quartile == self.market_class[self.period][1]:
            if self.balance > (current_price * self.shares) and self.buy_delay == 0 :
                if self.macd_pct < self.macd_buy_trip:
                    #set delay until next buy order
                    self.buy_delay = self.buy_wait
                    self.balance -= (current_price * self.shares)
                    actual_shares  = self.shares - (self.shares * self.commision)
                    buy = current_price
                    target = (buy * self.markup) + buy
                    stop = buy - (buy * self.stop_loss)
                    self.buy_log.append([self.time,buy])

                    new_position = {'master_index':len(self.positions),'age':0,'buy_period':self.period,'sell_period':0,'trade_pos': self.balance,'shares':actual_shares,'buy':buy,'cost':self.shares*buy,'target':target,'stop':stop,'status':"active",'actual':0,'score':0}
                    self.positions.append(new_position.copy())
                    #maintain a seperate subset of open positions to speed up the search to close the open positions
                    #after a long run there may be thousands of closed positions
                    #it was killing performance searching all of them for the few open positions at any given time
                    self.positions_open.append(new_position.copy())


        current_net_worth = 0

        #check for sold and stop loss orders
        sell = current_price * -1
        stop = current_price * -1
        updated = False
        for position in self.positions_open:
            #handle sold positions
            if position['status'] == "active" and position['target'] <= current_price: #and self.i_neg >= self.min_i_neg:
                updated = True
                position['status'] = "sold"
                position['actual'] = current_price
                sell = current_price
                position['sell_period'] = self.period
                self.wins += 1
                self.balance += position['target'] * (position['shares'] - (position['shares'] * self.commision))
                self.score_balance += ((position['target'] * (position['shares'] - (position['shares'] * self.commision))) / (position['buy'] * position['shares'])) * (pow(position['age'],self.stbf) / position['age'] )
                #update the position in the master list
                buy_period = position['buy_period']
                #self.positions = filter(lambda x: x.get('buy_period') != buy_period, self.positions) #delete the old record
                #self.positions.append(position.copy()) #and add the updated record
                self.positions[position['master_index']] = position.copy()
            #handle the stop orders
            elif position['status'] == "active" and (position['stop'] >= current_price or position['age'] >= self.stop_age):
                if position['stop'] >= current_price:
                    if self.enable_flash_crash_protection == True and self.market_class[self.period][1] == 1.0:
                        stop_order_executed = False
                        #convert the stop loss order into a short term hold position
                        position['age'] = self.stop_age - self.flash_crash_protection_delay
                        position['stop'] *= -1.0
                    else:
                        #stop loss
                        stop_order_executed = True
                        updated = True
                        position['status'] = "stop"
                        position['actual'] = current_price
                        stop = current_price
                        position['sell_period'] = self.period
                        self.loss += 1
                        self.buy_delay += self.buy_wait_after_stop_loss
                else:
                    #stop wait
                    stop_order_executed = True
                    updated = True
                    position['status'] = "stop"
                    position['actual'] = current_price
                    stop = current_price
                    position['sell_period'] = self.period
                    self.loss += 1 #- (position['actual'] / position['target'])  #fractional loss
                    self.buy_delay += self.buy_wait_after_stop_loss
                if stop_order_executed == True:
                    self.balance += position['actual'] * (position['shares'] - (position['shares'] * self.commision))
                    if position['age'] > 0:
                        self.score_balance += ((position['actual'] * (position['shares'] - (position['shares'] * self.commision))) / (position['buy'] * (position['shares'] + 0.0001))) * (pow(position['age'],self.stbf) / position['age'] )
                    #update the position in the master list
                    buy_period = position['buy_period']
                    #self.positions = filter(lambda x: x.get('buy_period') != buy_period, self.positions) #delete the old record
                    #self.positions.append(position.copy()) #and add the updated record
                    self.positions[position['master_index']] = position.copy()
            #handle active (open) positions
            elif position['status'] == "active":
                #position remains open, capture the current value
                current_net_worth += current_price * (position['shares'] - (position['shares'] * self.commision))
                position['age'] += 1

        #remove any closed positions from the open position subset
        if updated == True:
            self.positions_open = filter(lambda x: x.get('status') == 'active', self.positions_open)

        #add the balance to the net worth
        current_net_worth += self.balance
        if not self.score_only:
            if self.classified_market_data == False or self.quartile == self.market_class[self.period][1]:
                self.trigger_log.append([self.time,self.get_target()])
            self.net_worth_log.append([self.time,current_net_worth])
            if sell > 0:
                self.sell_log.append([self.time,sell])
            if stop > 0:
                self.stop_log.append([self.time,stop])
        return

    def get_target(self):
        #calculates the inverse macd
        #wolfram alpha used to transform the macd equation to solve for the trigger price:
        price = 0.0
        try:
            price = -1.0 * (100.0 *(self.wls+1)*(self.wll-1)*self.ema_long + (self.wll+1)*self.ema_short*(self.wls * (self.macd_buy_trip - 100) + self.macd_buy_trip + 100)) / (200 * (self.wls - self.wll))
            price -= 0.01 #subtract a penny to satisfy the trigger criteria
        except:
            price = 0.0
        if price < 0.0:
            price = 0.0
        #clamp the max value
        if price > self.history[0]:
            price = self.history[0]
        #clamp the min value (70% of ema_long)
        if price < self.ema_long * 0.7:
            price = self.ema_long * 0.7
        return price

    def macd(self):
        #wait until there is enough data to fill the moving windows
        if len(self.history) == self.wll:
            s = 0
            l = 0

            #calculate the ema weighting multipliers
            ema_short_mult = (2.0 / (self.wls + 1) )
            ema_long_mult = (2.0 / (self.wll + 1) )

            #bootstrap the ema calc using a simple moving avg if needed
            if self.ema_long == 0:
                for i in xrange(self.wll):
                    if i < self.wls:
                        s += self.history[i]
                    l += self.history[i]
                self.avg_ws = s / self.wls
                self.avg_wl = l / self.wll
                self.ema_long = self.avg_wl
                self.ema_short = self.avg_ws
            else:
                #calculate the long and short ema
                self.ema_long = (self.history[0] - self.ema_long) * ema_long_mult + self.ema_long
                self.ema_short = (self.history[0] - self.ema_short) * ema_short_mult + self.ema_short


            #calculate the absolute and pct differences between the
            #long and short emas
            self.macd_abs = self.ema_short - self.ema_long
            self.macd_pct = (self.macd_abs / self.ema_short) * 100


            """
            #track the number of sequential positive and negative periods
            if self.history[0] - self.history[1] > 0:
                self.i_neg = 0
                self.i_pos += 1
            if self.history[0] - self.history[1] < 0:
                self.i_pos = 0
                self.i_neg += 1
            """
            if not self.score_only:
                #track the max & min macd pcts (metric)
                if self.macd_pct > self.metric_macd_pct_max:
                    self.metric_macd_pct_max = self.macd_pct
                if self.macd_pct < self.metric_macd_pct_min:
                    self.metric_macd_pct_min = self.macd_pct
        else:
            self.ema_short = self.history[0]
            self.ema_long = self.history[0]
            self.macd_pct = 0

        #log the indicators
        if not self.score_only:
            self.macd_pct_log.append([self.time,self.macd_pct])
            self.wl_log.append([self.time,self.ema_long])
            self.ws_log.append([self.time,self.ema_short])


    def display(self):
        #used for debug
        print ",".join(map(str,[self.history[0],self.macd_pct,self.buy_wait]))

    def input(self,time_stamp,record):
        #self.time = int(time.mktime(time.strptime(time_stamp))) * 1000
        self.time = int(time_stamp * 1000)
        self.input_log.append([self.time,record])

        ###Date,Sell,Buy,Last,Vol,High,Low,###
        self.history.insert(0,record)
        if len(self.history) > self.wll:
            self.history.pop()  #maintain a moving window of
                    #the last wll records
        self.macd()     #calc macd
        self.ai()       #call the trade ai
        self.period += 1    #increment the period counter
        #self.display()
        return

    def log_orders(self,filename=None):
        self.order_history = ""
        print "log_orders: sorting data"
        self.positions = sorted(self.positions, key=itemgetter('buy_period'),reverse=True)
        if len(self.positions) > 0:
            keys = self.positions[0].keys()
        #write the header
        self.order_history = "<table class='imgtbl'>\n"
        self.order_history +="<tr>"
        for key in keys:
            self.order_history +="<th>%s</tht>"%key
        self.order_history +="</tr>\n"

        #only htmlize the last positions so the browser doesn't blow up ;)
        reported_position_count_limit = 200
        reported_position_count = 0
        print "log_orders: generating html table for %s positions"%(len(self.positions))
        for p in self.positions:
            if reported_position_count >= reported_position_count_limit:
                break

            #I dont care about the dumped positions, they're not real transactions anyway.
            #They're only generated to calculate/report the current account value.
            if p['status']!='dumped':
                reported_position_count += 1
                self.order_history +="<tr>"

            for key in keys:
                if p.has_key(key):
                    #I dont care about the dumped positions, they're not real transactions anyway.
                    #They're only generated to calculate/report the current account value.
                    if p['status']!='dumped':
                        if p['status']=='stop':
                            color = 'r'
                        elif p['status']=='dumped': #Im leaving this here in case I want to turn it back on.
                            color = 'y'
                        elif p['status']=='sold':
                            color = 'g'
                        else:
                            color = 'b'
                        self.order_history +="<td class='%s'>"%color
                        if type(p[key]) == type(1.0):
                            self.order_history += "%.2f"% round(p[key],2)
                        else:
                            self.order_history += str(p[key])

                        self.order_history +="</td>"

                elif p['status']!='dumped':
                    self.order_history +="<td>N/A</td>"

            if p['status']!='dumped':
                self.order_history +="</tr>\n"

        self.order_history += "</table>"
        return

    def log_transactions(self,filename):
        #log the transactions to a file
        #used with excel / gdocs to chart price and buy/sell indicators
        f = open(filename,'w')

        for i in xrange(len(self.input_log)):
            for position in self.positions:
                if position['buy_period'] == i:
                    #print position['buy_period'],i
                    self.input_log[i].append('buy')
                    self.input_log[i].append(position['sell_period'] - position['buy_period'])
                    self.input_log[i].append(position['status'])
                    self.input_log[i].append(i)
                if position['sell_period'] == i:
                    self.input_log[i].append('sell')
                    self.input_log[i].append('0')
                    self.input_log[i].append(position['status'])
                    self.input_log[i].append(i)
            r = ",".join(map(str,self.input_log[i]))
            f.write(r)
            f.write('\n')
        f.close()
        return

    def compress_log(self,log,lossless_compression = False):
        #removes records with no change in price, before and after record n
        compressible = True
        while compressible:
            compressible = False
            ret_log = []
            for i in xrange(len(log)):
                if type(log[i][1]) == float:
                    log[i][1] = float("%.3f"%log[i][1])
                if i >= 1 and i < len(log) - 1:
                    if log[i-1][1] == log[i][1] and log[i+1][1] == log[i][1]:
                        compressible = True #no change in value before or after, omit record
                    else:
                        ret_log.append(log[i])
                else:
                    ret_log.append(log[i])
            log = ret_log

        if lossless_compression == True:
            return ret_log

        while len(log) > 2000:
            avg = log[0][1]
            avg = (log[0][1] - avg) * 0.2 + avg
            ret_log = [log[0]]  #capture the first record
            for i in xrange(1,len(log),2):
                #find which sample that deviates the most from the average
                a = abs(log[i][1] - avg)
                b = abs(log[i-1][1] - avg)
                if a > b:
                    ret_log.append(log[i])
                else:
                    ret_log.append(log[i-1])
                #update the moving average
                avg = (log[i-1][1] - avg) * 0.2 + avg
                avg = (log[i][1] - avg) * 0.2 + avg
            ret_log.append(log[len(log)-1]) #make sure the last record is captured
            log = ret_log

        return ret_log

    def chart(self,template,filename,periods=-1,basic_chart=False):
        self.log_orders()

        f = open(template,'r')
        tmpl = f.read()
        f.close()

        if periods < 0:
            periods = self.period * -1
        else:
            periods *= -1

        #insert all quartiles at the begining of the market class data to ensure correct
        #chart scaling. This covers the case where the chart period doesn't see all quartiles
        mc = self.market_class[periods:]
        t = mc[0][0]
        for i in range(0,4):
            t += 1
            q = (i + 1) / 4.0
            mc.insert(0,[t,q])

        print "chart: compressing data"
        if not basic_chart:
            wl = str(self.compress_log(self.wl_log[periods:])).replace('L','')
            ws = str(self.compress_log(self.ws_log[periods:])).replace('L','')
            net_worth = str(self.compress_log(self.net_worth_log[periods:],lossless_compression = True)).replace('L','')
        else:
            wl = str([])
            ws = str([])
            net_worth = str([])

        macd_pct = str(self.compress_log(self.macd_pct_log[periods:])).replace('L','')
        input = str(self.compress_log(self.input_log[periods:])).replace('L','')
        volatility_quartile = str(self.compress_log(mc,lossless_compression = True)).replace('L','')

        buy = str([])
        sell = str([])
        stop = str([])
        trigger_price = str([])

        if periods == self.period:
            buy = str(self.buy_log[periods:]).replace('L','')
            sell = str(self.sell_log[periods:]).replace('L','')
            stop = str(self.stop_log[periods:]).replace('L','')
            trigger_price = str(self.compress_log(self.trigger_log[periods:],lossless_compression = True)).replace('L','')
        else:
            print "chart: selecting data"
            #get the timestamp for the start index
            time_stamp = self.input_log[periods:periods+1][0][0]
            #search the following for the time stamp
            for i in xrange(len(self.buy_log)):
                if self.buy_log[i][0] >= time_stamp:
                    buy = str(self.buy_log[i:]).replace('L','')
                    break
            for i in xrange(len(self.sell_log)):
                if self.sell_log[i][0] >= time_stamp:
                    sell = str(self.sell_log[i:]).replace('L','')
                    break
            for i in xrange(len(self.stop_log)):
                if self.stop_log[i][0] >= time_stamp:
                    stop = str(self.stop_log[i:]).replace('L','')
                    break
            for i in xrange(len(self.trigger_log)):
                if self.trigger_log[i][0] >= time_stamp:
                    trigger_price = str(self.trigger_log[i:]).replace('L','')
                    break

        print "chart: filling the template"
        tmpl = tmpl.replace("{LAST_UPDATE}",time.ctime())
        tmpl = tmpl.replace("{PRICES}",input)
        tmpl = tmpl.replace("{WINDOW_LONG}",wl)
        tmpl = tmpl.replace("{WINDOW_SHORT}",ws)
        tmpl = tmpl.replace("{MACD_PCT}",macd_pct)
        tmpl = tmpl.replace("{BUY}",buy)
        tmpl = tmpl.replace("{SELL}",sell)
        tmpl = tmpl.replace("{STOP}",stop)
        tmpl = tmpl.replace("{NET_WORTH}",net_worth)
        tmpl = tmpl.replace("{TRIGGER_PRICE}",trigger_price)
        tmpl = tmpl.replace("{METRICS_REPORT}",self.metrics_report().replace('\n','<BR>'))
        tmpl = tmpl.replace("{ORDERS_REPORT}",self.order_history)
        tmpl = tmpl.replace("{VOLATILITY_QUARTILE}",volatility_quartile)


        print "chart: writing the data to a file"
        f = open(filename,'w')
        f.write(tmpl)
        f.close()
        return



def test():
    te = trade_engine()
    #set the trade engine class vars

    te.shares = 0.1
    te.wll = 242
    te.wls = 1
    te.buy_wait = 0
    te.markup = 0.01
    te.stop_loss = 0.128
    te.stop_age = 2976
    te.macd_buy_trip = -0.02
    te.min_i_neg = 2
    te.min_i_pos = 0
    te.buy_wait_after_stop_loss = 0

    for row in d[1:]:
        r = row.split(',')[1] #last
        t = row.split(',')[0] #time
        te.input(float(t),float(r))

    return te


if __name__ == "__main__":

    __appversion__ = "0.02a"
    print "Bitcoin trade simulator profiler v%s"%__appversion__

    print " -- this is a test script to profile the performance of bct.py"
    print " -- the trade results should be ignored as the trade strategy inputs"
    print " are designed to stress the module with many trade positions"
    print ""
    print "Profiling bct...(This is going to take a while)"
    #open the history file
    f = open("./datafeed/bcfeed_mtgoxUSD_1min.csv",'r')
    d = f.readlines()
    f.close()


    import hotshot,hotshot.stats
    prof = hotshot.Profile("bct.prof")

    te = prof.runcall(test)
    prof.close()
    stats = hotshot.stats.load("bct.prof")
    stats.strip_dirs()
    stats.sort_stats('time','calls')
    stats.print_stats(20)


    print "Score:",te.score()
    print "Closing Balance:",te.balance
    print "Transaction Count: ",len(te.positions)

    #Commented out the follwing reports -- they generate very large files and in the case of this test script of limited use.
    #print "Generating reports..."
    #te.log_transactions('./report/profile_transactions.csv')
    #te.log_orders('./report/profile_orders.csv')
    #te.chart("./report/chart.templ","./report/chart_profile.html")
    print "Done."

